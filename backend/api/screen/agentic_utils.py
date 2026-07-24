"""backend.api.screen.agentic_utils

Utilities for the GREP-Agent style "screening + critical" workflow.

We keep this module small and dependency-free so routers can reuse the helpers
for title/abstract and fulltext pipelines.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Literal
from typing import TypeVar


@dataclass
class ParsedAgentXML:
    answer: str
    confidence: float
    rationale: str
    parse_ok: bool
    missing_answer: bool
    missing_confidence: bool
    missing_rationale: bool
    # Evidence fields (only populated for fulltext screening prompts)
    evidence_sentences: list[int] = field(default_factory=list)
    evidence_tables: list[int] = field(default_factory=list)
    evidence_figures: list[int] = field(default_factory=list)


_TAG_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _tag_re(tag: str) -> re.Pattern[str]:
    if tag not in _TAG_RE_CACHE:
        _TAG_RE_CACHE[tag] = re.compile(
            rf"<{tag}>(.*?)</{tag}>", re.IGNORECASE | re.DOTALL,
        )
    return _TAG_RE_CACHE[tag]


def _parse_int_list(text: str) -> list[int]:
    """Parse a comma-separated string of integers (e.g. '2,5,11') into a list."""
    out: list[int] = []
    for part in (text or '').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            continue
    # stable unique
    seen: set = set()
    uniq: list[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def parse_agent_xml(text: str) -> ParsedAgentXML:
    """Parse <answer>, <confidence>, <rationale> (and optional evidence) tags from model output."""

    raw = (text or '').strip()
    ans_m = _tag_re('answer').search(raw)
    conf_m = _tag_re('confidence').search(raw)
    rat_m = _tag_re('rationale').search(raw)
    ev_sent_m = _tag_re('evidence_sentences').search(raw)
    ev_tbl_m = _tag_re('evidence_tables').search(raw)
    ev_fig_m = _tag_re('evidence_figures').search(raw)

    answer = (ans_m.group(1).strip() if ans_m else '')
    rationale = (rat_m.group(1).strip() if rat_m else '')

    conf_val = 0.0
    if conf_m:
        try:
            conf_val = float(conf_m.group(1).strip())
        except Exception:
            conf_val = 0.0
    conf_val = max(0.0, min(1.0, conf_val))

    evidence_sentences = _parse_int_list(
        ev_sent_m.group(1) if ev_sent_m else '',
    )
    evidence_tables = _parse_int_list(ev_tbl_m.group(1) if ev_tbl_m else '')
    evidence_figures = _parse_int_list(ev_fig_m.group(1) if ev_fig_m else '')

    missing_answer = not bool(ans_m and answer.strip())
    missing_confidence = not bool(conf_m)
    if conf_m:
        try:
            float(conf_m.group(1).strip())
        except (TypeError, ValueError):
            missing_confidence = True
    missing_rationale = not bool(rat_m and rationale)
    parse_ok = (not missing_answer) and (not missing_confidence)
    return ParsedAgentXML(
        answer=answer,
        confidence=conf_val,
        rationale=rationale,
        parse_ok=parse_ok,
        missing_answer=missing_answer,
        missing_confidence=missing_confidence,
        missing_rationale=missing_rationale,
        evidence_sentences=evidence_sentences,
        evidence_tables=evidence_tables,
        evidence_figures=evidence_figures,
    )


AgentStage = Literal['screening', 'critical']
TCallMetadata = TypeVar('TCallMetadata')


class AgentResponseError(ValueError):
    """Raised when an LLM response still violates its stage contract after repair.

    The repaired response is retained so callers that support partial suggestions
    can persist the usable fields and show precise warnings to reviewers.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_response: str = '',
        parsed: ParsedAgentXML | None = None,
        metadata: object | None = None,
        missing_fields: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.parsed = parsed
        self.metadata = metadata
        self.missing_fields = list(missing_fields or [])


def validate_agent_response(
    parsed: ParsedAgentXML,
    *,
    stage: AgentStage,
) -> list[str]:
    """Return contract violations for a parsed screening or critical response."""
    missing: list[str] = []
    if parsed.missing_answer:
        missing.append('answer')
    if parsed.missing_confidence:
        missing.append('confidence')
    if stage == 'screening' and parsed.missing_rationale:
        missing.append('rationale')
    return missing


def build_repair_prompt(
    *,
    raw_response: str,
    stage: AgentStage,
    original_prompt: str = '',
) -> str:
    """Ask the model to reformat an incomplete response without changing its judgment."""
    if stage == 'screening':
        schema = (
            '<answer>exact selected option</answer>\n'
            '<confidence>number from 0 to 1</confidence>\n'
            '<rationale>non-empty concise evidence-based explanation</rationale>'
        )
    else:
        schema = (
            '<answer>exact selected option</answer>\n'
            '<confidence>number from 0 to 1</confidence>'
        )
    context = original_prompt.strip()
    return f"""Your previous response did not match the required output contract.
Use the original task and allowed options below. Preserve the same judgment when it
is recoverable; otherwise make the best supported judgment from the original task.
Return ONLY these XML tags with valid, non-empty values:
{schema}

Original task and allowed options:
{context or '(not available)'}

Previous response:
{raw_response}
"""


async def call_and_parse_agent_response(
    prompt: str,
    *,
    stage: AgentStage,
    call_llm: Callable[[str], Awaitable[tuple[str, TCallMetadata]]],
) -> tuple[str, ParsedAgentXML, TCallMetadata, bool]:
    """Call an agent and make one repair attempt when its stage contract is invalid."""
    raw, metadata = await call_llm(prompt)
    parsed = parse_agent_xml(raw)
    missing = validate_agent_response(parsed, stage=stage)
    if not missing:
        return raw, parsed, metadata, False

    repair_prompt = build_repair_prompt(
        raw_response=raw,
        stage=stage,
        original_prompt=prompt,
    )
    repaired_raw, repaired_metadata = await call_llm(repair_prompt)
    repaired = parse_agent_xml(repaired_raw)
    repaired_missing = validate_agent_response(repaired, stage=stage)
    if repaired_missing:
        fields = ', '.join(repaired_missing)
        raise AgentResponseError(
            f'{stage.capitalize()} agent response missing or invalid fields after repair: {fields}',
            raw_response=repaired_raw,
            parsed=repaired,
            metadata=repaired_metadata,
            missing_fields=repaired_missing,
        )
    return repaired_raw, repaired, repaired_metadata, True


def resolve_option(raw_answer: str, options: list[str]) -> str:
    """Resolve a model answer to one of the provided options (best-effort)."""
    ans = (raw_answer or '').strip()
    if not ans:
        return ans

    # Exact match first
    for opt in options or []:
        if ans == opt:
            return opt

    # Case-insensitive exact
    ans_l = ans.lower()
    for opt in options or []:
        if ans_l == (opt or '').lower():
            return opt

    # Substring containment (mirrors existing CAN-SR JSON screening logic)
    for opt in options or []:
        if (opt or '').lower() in ans_l:
            return opt

    return ans


def build_critical_options(*, all_options: list[str], screening_answer: str) -> list[str]:
    """Forced alternatives: (all_options - {screening_answer}) + ["None of the above"]."""
    base = [o for o in (all_options or []) if (o or '').strip()]
    sa = (screening_answer or '').strip()
    if sa:
        base = [o for o in base if o.strip() != sa]
    base.append('None of the above')
    # stable unique
    seen = set()
    out = []
    for o in base:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out
