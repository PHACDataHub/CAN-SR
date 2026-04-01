"""backend.api.screen.agentic_utils

Utilities for the GREP-Agent style "screening + critical" workflow.

We keep this module small and dependency-free so routers can reuse the helpers
for title/abstract and fulltext pipelines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedAgentXML:
    answer: str
    confidence: float
    rationale: str
    parse_ok: bool


_TAG_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _tag_re(tag: str) -> re.Pattern[str]:
    if tag not in _TAG_RE_CACHE:
        _TAG_RE_CACHE[tag] = re.compile(rf"<{tag}>(.*?)</{tag}>", re.IGNORECASE | re.DOTALL)
    return _TAG_RE_CACHE[tag]


def parse_agent_xml(text: str) -> ParsedAgentXML:
    """Parse <answer>, <confidence>, <rationale> tags from model output."""

    raw = (text or "").strip()
    ans_m = _tag_re("answer").search(raw)
    conf_m = _tag_re("confidence").search(raw)
    rat_m = _tag_re("rationale").search(raw)

    answer = (ans_m.group(1).strip() if ans_m else "")
    rationale = (rat_m.group(1).strip() if rat_m else "")

    conf_val = 0.0
    if conf_m:
        try:
            conf_val = float(conf_m.group(1).strip())
        except Exception:
            conf_val = 0.0
    conf_val = max(0.0, min(1.0, conf_val))

    parse_ok = bool(ans_m and conf_m)
    return ParsedAgentXML(answer=answer, confidence=conf_val, rationale=rationale, parse_ok=parse_ok)


def resolve_option(raw_answer: str, options: list[str]) -> str:
    """Resolve a model answer to one of the provided options (best-effort)."""
    ans = (raw_answer or "").strip()
    if not ans:
        return ans

    # Exact match first
    for opt in options or []:
        if ans == opt:
            return opt

    # Case-insensitive exact
    ans_l = ans.lower()
    for opt in options or []:
        if ans_l == (opt or "").lower():
            return opt

    # Substring containment (mirrors existing CAN-SR JSON screening logic)
    for opt in options or []:
        if (opt or "").lower() in ans_l:
            return opt

    return ans


def build_critical_options(*, all_options: list[str], screening_answer: str) -> list[str]:
    """Forced alternatives: (all_options - {screening_answer}) + ["None of the above"]."""
    base = [o for o in (all_options or []) if (o or "").strip()]
    sa = (screening_answer or "").strip()
    if sa:
        base = [o for o in base if o.strip() != sa]
    base.append("None of the above")
    # stable unique
    seen = set()
    out = []
    for o in base:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out
