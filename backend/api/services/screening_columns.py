"""Single source of truth for screening and parameter answer column names.

Answer columns are derived from the criterion question (or parameter name) and
are created dynamically on the citation table. Three rules matter to every
consumer, and re-deriving them per call site is how they drift apart:

1. Stage. Current columns are stage-qualified (``llm_l1_*``/``human_l1_*``),
   but reviews created before that change stored unqualified ``llm_*``/
   ``human_*`` columns. Readers must therefore try the stage-qualified name
   first and fall back to the legacy one; writers only ever use the
   stage-qualified name.
2. Length. Postgres silently truncates identifiers to 63 bytes, so a long
   question is stored under a name the untruncated Python string never matches.
   Every name produced here is pre-truncated the same way Postgres would.
3. Existence. A name is only usable if the physical column is really there,
   so callers resolve against live table metadata rather than assuming.
"""
from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass

from .cit_db_service import snake_case
from .cit_db_service import snake_case_param

# Postgres NAMEDATALEN - 1. Longer identifiers are truncated on write, so the
# same truncation has to happen before we look a column up by name.
MAX_IDENTIFIER_BYTES = 63

STAGES = ('l1', 'l2')


def truncate_identifier(name: str) -> str:
    """Truncate to what Postgres actually stores, on a character boundary."""
    encoded = name.encode('utf-8')
    if len(encoded) <= MAX_IDENTIFIER_BYTES:
        return name
    return encoded[:MAX_IDENTIFIER_BYTES].decode('utf-8', errors='ignore')


def criterion_key(question: str) -> str:
    """Stable slug for a screening question, shared by every column name."""
    return snake_case(str(question or ''), max_len=56)


def parameter_key(name: str) -> str:
    """Stable slug for an extracted parameter.

    Derived from snake_case_param so the key matches what writers actually
    store: that helper caps the whole ``llm_param_*`` column at 60 characters,
    which truncates the slug to 50 rather than the 52 it starts from.
    """
    return snake_case_param(str(name or '')).removeprefix('llm_param_')


def _stage(stage: str) -> str:
    return 'l2' if str(stage or '').strip().lower() == 'l2' else 'l1'


@dataclass(frozen=True)
class ScreeningColumns:
    """Candidate column names for one criterion, in priority order."""

    key: str
    human: str
    llm: str
    legacy_human: str
    legacy_llm: str

    @property
    def human_candidates(self) -> tuple[str, ...]:
        return (self.human, self.legacy_human)

    @property
    def llm_candidates(self) -> tuple[str, ...]:
        return (self.llm, self.legacy_llm)


def screening_columns(stage: str, question: str) -> ScreeningColumns:
    """Return every name a criterion's answers may be stored under."""
    key = criterion_key(question)
    prefix = _stage(stage)
    if not key:
        return ScreeningColumns(
            key='', human='human_col', llm='llm_col',
            legacy_human='human_col', legacy_llm='llm_col',
        )
    return ScreeningColumns(
        key=key,
        human=truncate_identifier(f'human_{prefix}_{key}'),
        llm=truncate_identifier(f'llm_{prefix}_{key}'),
        legacy_human=truncate_identifier(f'human_{key}'),
        legacy_llm=truncate_identifier(f'llm_{key}'),
    )


@dataclass(frozen=True)
class ParameterColumns:
    key: str
    human: str
    llm: str


def parameter_columns(name: str) -> ParameterColumns:
    key = parameter_key(name)
    if not key:
        return ParameterColumns(key='', human='human_param', llm='llm_param_param')
    return ParameterColumns(
        key=key,
        human=truncate_identifier(f'human_param_{key}'),
        llm=truncate_identifier(f'llm_param_{key}'),
    )


def column_index(columns: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """Index live table metadata by case-folded name -> real name."""
    index: dict[str, str] = {}
    for column in columns or ():
        name = str((column or {}).get('column_name') or '').strip()
        if name:
            index.setdefault(name.casefold(), name)
    return index


def resolve_existing(
    existing: Mapping[str, str], candidates: Iterable[str],
) -> str | None:
    """Return the first candidate that exists, using the real column casing."""
    for candidate in candidates:
        if not candidate:
            continue
        found = existing.get(candidate.casefold())
        if found:
            return found
    return None
