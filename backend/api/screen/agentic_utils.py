"""backend.api.screen.agentic_utils

Utilities for the GREP-Agent style "screening + critical" workflow.

We keep this module small and dependency-free so routers can reuse the helpers
for title/abstract and fulltext pipelines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from typing import List
from typing import Optional


@dataclass
class ParsedAgentXML:
    answer: str
    confidence: float
    rationale: str
    parse_ok: bool
    missing_answer: bool
    missing_confidence: bool
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
    parse_ok = (not missing_answer) and (not missing_confidence)
    return ParsedAgentXML(
        answer=answer,
        confidence=conf_val,
        rationale=rationale,
        parse_ok=parse_ok,
        missing_answer=missing_answer,
        missing_confidence=missing_confidence,
        evidence_sentences=evidence_sentences,
        evidence_tables=evidence_tables,
        evidence_figures=evidence_figures,
    )


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
