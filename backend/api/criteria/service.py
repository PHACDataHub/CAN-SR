"""Parsing, migration, serialization, and compatibility projection for criteria."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any
from typing import Literal

import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .models import CriteriaConfigV2

LEGACY_KEYS = {'include', 'criteria', 'l2_criteria', 'parameters'}
LEGACY_ONLY_KEYS = {'include', 'criteria', 'l2_criteria'}
MAX_YAML_BYTES = 1_000_000


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra='forbid')

    severity: Literal['info', 'warning']
    code: str
    source_path: list[str | int] = Field(default_factory=list)
    target_path: list[str | int] = Field(default_factory=list)
    message: str
    requires_confirmation: bool = False


class MigrationStats(BaseModel):
    l1: int = 0
    l2: int = 0
    parameters: int = 0


class CriteriaLoadResult(BaseModel):
    criteria: CriteriaConfigV2
    source_format: Literal['criteria_v2', 'legacy_yaml_v1']
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    requires_confirmation: bool = False
    fingerprint: str | None = None
    stats: MigrationStats | None = None


class _IdAllocator:
    def __init__(self) -> None:
        self.used: set[str] = set()

    def allocate(self, prefix: str, value: str, fallback: str) -> str:
        normalized = unicodedata.normalize(
            'NFKD', value,
        ).encode('ascii', 'ignore').decode()
        slug = re.sub(
            r'[^a-z0-9]+', '_', normalized.lower(),
        ).strip('_') or fallback
        base = f'{prefix}{slug}'[:63].rstrip('_')
        if len(base) < 3:
            base = f'{prefix}{fallback}'[:63]
        candidate = base
        suffix = 2
        while candidate in self.used:
            marker = f'_{suffix}'
            candidate = f'{base[:64 - len(marker)]}{marker}'
            suffix += 1
        self.used.add(candidate)
        return candidate


class CriteriaConfigurationService:
    """Pure canonical criteria operations shared by API and persistence adapters."""

    def parse_yaml(self, content: str, *, source_kind: str = 'yaml_import') -> CriteriaLoadResult:
        if len(content.encode('utf-8')) > MAX_YAML_BYTES:
            raise ValueError('criteria YAML exceeds the 1 MB limit')
        try:
            raw = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ValueError(f'invalid criteria YAML: {exc}') from exc
        if not isinstance(raw, dict):
            raise ValueError('criteria YAML root must be a mapping')
        return self.normalize(raw, source_kind=source_kind)

    def normalize(self, raw: dict[str, Any], *, source_kind: str = 'backend_load') -> CriteriaLoadResult:
        version = raw.get('schema_version')
        if version == 2:
            mixed = LEGACY_ONLY_KEYS.intersection(raw)
            if mixed:
                raise ValueError(
                    f'v2 criteria cannot contain legacy keys: {sorted(mixed)}',
                )
            return CriteriaLoadResult(
                criteria=CriteriaConfigV2.model_validate(raw),
                source_format='criteria_v2',
            )
        if version is not None:
            raise ValueError(
                f'unsupported criteria schema_version: {version!r}',
            )
        if not LEGACY_KEYS.intersection(raw):
            raise ValueError('unrecognized criteria format')
        return self._migrate_legacy(raw, source_kind=source_kind)

    def export_yaml(self, criteria: CriteriaConfigV2 | dict[str, Any]) -> str:
        model = criteria if isinstance(
            criteria, CriteriaConfigV2,
        ) else CriteriaConfigV2.model_validate(criteria)
        payload = model.model_dump(mode='json', exclude_none=True)
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)

    def build_compatibility_projection(
        self, criteria: CriteriaConfigV2 | dict[str, Any],
    ) -> dict[str, Any]:
        model = criteria if isinstance(
            criteria, CriteriaConfigV2,
        ) else CriteriaConfigV2.model_validate(criteria)

        def stage(items):
            return {
                'questions': [item.question for item in items],
                'possible_answers': [[answer.label for answer in item.answers] for item in items],
                'additional_infos': [
                    '\n\n'.join(
                        f'For articles matching <{answer.label}> we answer "{answer.label}":\n'
                        f'<{answer.label}>\n{answer.context or ""}\n</{answer.label}>'
                        for answer in item.answers
                    )
                    for item in items
                ],
                'items': [item.model_dump(mode='json', exclude_none=True) for item in items],
            }

        parameter_items = [
            item.model_dump(
                mode='json', exclude_none=True,
            ) for item in model.parameters
        ]
        categories: list[str] = []
        grouped: dict[str, list[Any]] = {}
        for item in model.parameters:
            category = item.legacy_category or 'Parameters'
            if category not in grouped:
                categories.append(category)
                grouped[category] = []
            grouped[category].append(item)
        return {
            'schema_version': 2,
            'l1': {'include': model.citation_fields.l1_include, **stage(model.l1)},
            'l2': stage(model.l2),
            'parameters': {
                'categories': categories,
                'possible_parameters': [[item.name for item in grouped[category]] for category in categories],
                'descriptions': [
                    [f'Parameter {item.name} are described as <desc>{item.description}</desc>.' for item in grouped[category]]
                    for category in categories
                ],
                'items': parameter_items,
            },
        }

    def _migrate_legacy(self, legacy: dict[str, Any], *, source_kind: str) -> CriteriaLoadResult:
        # Reserved for source-specific telemetry; migration remains pure.
        del source_kind
        diagnostics: list[Diagnostic] = []
        item_ids = _IdAllocator()

        include = legacy.get('include', [])
        if not isinstance(include, list) or any(not isinstance(value, str) or not value.strip() for value in include):
            raise ValueError(
                'legacy include must be a list of non-empty strings',
            )
        normalized_include = list(
            dict.fromkeys(
                value.strip() for value in include
            ),
        )
        if len(normalized_include) != len(include):
            diagnostics.append(
                Diagnostic(
                    severity='warning', code='duplicate_include_fields_removed',
                    source_path=['include'], target_path=['citation_fields', 'l1_include'],
                    message='Duplicate citation fields were removed while preserving order.',
                ),
            )

        def questions(key: str, stage: str) -> list[dict[str, Any]]:
            block = legacy.get(key, {})
            if block is None:
                block = {}
            if not isinstance(block, dict):
                raise ValueError(f'legacy {key} must be a mapping')
            output = []
            for question_index, (question, answers) in enumerate(block.items()):
                if not isinstance(question, str) or not question.strip() or not isinstance(answers, dict):
                    raise ValueError(
                        f'legacy {key} questions and answers must be mappings of non-empty strings',
                    )
                option_ids = _IdAllocator()
                converted_answers = []
                decisions: set[str] = set()
                for answer_index, (label, context) in enumerate(answers.items()):
                    if not isinstance(label, str) or not label.strip() or not isinstance(context, str):
                        raise ValueError(
                            f'legacy {key} answer labels and contexts must be strings',
                        )
                    exclude = bool(
                        re.search(
                            r'(?i)(?:\(exclude\)|\[exclude\]|^\s*exclude\s*$)', label,
                        ),
                    )
                    decision = 'exclude' if exclude else 'include'
                    decisions.add(decision)
                    diagnostics.append(
                        Diagnostic(
                            severity='warning' if exclude else 'info',
                            code='decision_inferred_exclude' if exclude else 'decision_defaulted_include',
                            source_path=[key, question, label],
                            target_path=[
                                stage, question_index,
                                'answers', answer_index, 'decision',
                            ],
                            message=(
                                'This answer was marked Exclude from a legacy text marker.' if exclude
                                else 'This answer defaulted to Include because no legacy exclusion marker was present.'
                            ),
                            requires_confirmation=exclude,
                        ),
                    )
                    converted_answers.append({
                        'id': option_ids.allocate('', label, f'answer_{answer_index + 1}'),
                        'label': label.strip(), 'context': context.strip() or None, 'decision': decision,
                    })
                if len(converted_answers) < 2:
                    raise ValueError(
                        f'legacy {key} question {question!r} must have at least two answers',
                    )
                if decisions != {'include', 'exclude'}:
                    diagnostics.append(
                        Diagnostic(
                            severity='warning', code='unbalanced_screening_decisions',
                            source_path=[key, question], target_path=[
                                stage, question_index, 'answers',
                            ],
                            message='This question does not contain both Include and Exclude answers.',
                            requires_confirmation=True,
                        ),
                    )
                output.append({
                    'id': item_ids.allocate(f'q_{stage}_', question, f'question_{question_index + 1}'),
                    'question': question.strip(), 'answers': converted_answers, 'trigger': {'all': []},
                })
            return output

        parameters = legacy.get('parameters', {})
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            raise ValueError('legacy parameters must be a mapping')
        converted_parameters = []
        parameter_index = 0
        for category, values in parameters.items():
            if not isinstance(category, str) or not category.strip() or not isinstance(values, dict):
                raise ValueError(
                    'legacy parameter categories must map to parameter mappings',
                )
            for name, description in values.items():
                if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
                    raise ValueError(
                        'legacy parameter names and descriptions must be non-empty strings',
                    )
                parameter_index += 1
                converted_parameters.append({
                    'id': item_ids.allocate('p_', f'{category}_{name}', f'parameter_{parameter_index}'),
                    'name': name.strip(), 'description': description.strip(), 'type': 'text',
                    'unit_instructions': None, 'calculation': None, 'trigger': {'all': []},
                    'legacy_category': category.strip(),
                })

        l1 = questions('criteria', 'l1')
        l2 = questions('l2_criteria', 'l2')
        criteria = CriteriaConfigV2.model_validate({
            'schema_version': 2,
            'citation_fields': {'l1_include': normalized_include, 'doi': None},
            'l1': l1, 'l2': l2, 'parameters': converted_parameters,
        })
        canonical_source = json.dumps(
            legacy, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        )
        fingerprint = f'sha256:{hashlib.sha256(canonical_source.encode()).hexdigest()}'
        return CriteriaLoadResult(
            criteria=criteria,
            source_format='legacy_yaml_v1',
            diagnostics=diagnostics,
            requires_confirmation=any(
                item.requires_confirmation for item in diagnostics
            ),
            fingerprint=fingerprint,
            stats=MigrationStats(
                l1=len(l1), l2=len(
                    l2,
                ), parameters=len(converted_parameters),
            ),
        )


criteria_configuration_service = CriteriaConfigurationService()
