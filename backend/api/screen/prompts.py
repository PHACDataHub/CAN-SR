from __future__ import annotations
PROMPT_JSON_TEMPLATE = """
You are a highly critical, helpful scientific evaluator completing an academic review. Your job is to screen a citation and decide whether to
include or exclude it according to a single question and a fixed set of options.

Answer the question "{question}" for the following citation:

{cit}

The available options (exact text) are:
{options}

Additional guidance to consider:
{xtra}

Output requirement:
Respond with a JSON object containing these keys:
- "selected": the exact option string you selected (must match one of the options above; if none fits, pick the closest option and report a low confidence score)
- "explanation": a concise explanation (1-4 sentences) of why you selected that option
- "confidence": a floating number between 0 and 1 (inclusive) representing your estimated confidence for the selected option

JSON object format:
{{
  "selected": "Include",
  "explanation": "The study meets the inclusion criteria because ...",
  "confidence": 0.72
}}

Keep the response strictly as a JSON object that matches the schema above. Do not wrap the response in Markdown code fences or add language tags (e.g., ```json). Return only raw JSON starting with {{ and ending with }}.
"""

PROMPT_JSON_TEMPLATE_FULLTEXT = """
You are assisting with a scientific full-text screening task. Evaluate the question "{question}" against the paper content provided as numbered sentences (e.g., "[0] ...", "[1] ...").

Context:
- Options (choose exactly one of these strings):
{options}

- Additional guidance:
{xtra}

- Full text (numbered sentences):
{fulltext}

- Tables (numbered):
{tables}

- Figures (numbered; captions correspond to images provided alongside this message):
{figures}

Respond with a JSON object containing these keys:
- "selected": the exact option string you selected (must match one of the options above; if none fits, pick the closest option and report a low confidence score)
- "explanation": a concise explanation (1-4 sentences) of why you selected that option
- "confidence": a floating number between 0 and 1 (inclusive) representing your estimated confidence for the selected option
- "evidence_sentences": an array of integers indicating the sentence indices you used as evidence (e.g. [2, 5]). If there is low confidence, return an empty array [].
- "evidence_tables": an array of integers indicating the table numbers you used (e.g. [1, 3]) or [] if none.
- "evidence_figures": an array of integers indicating the figure numbers you used (e.g. [2]) or [] if none.
- If a table or figure is referenced, ensure the explanation references the table/figure number and what was extracted from it.

JSON object format:
{{
  "selected": "<one of the provided options>",
  "explanation": "<1-4 sentences explaining the choice>",
  "confidence": <float 0..1>,
  "evidence_sentences": [<indices of sentences used as evidence>],
  "evidence_tables": [<table numbers used>],
  "evidence_figures": [<figure numbers used>]
}}

Notes:
- Keep the response strictly as a JSON object that matches the schema above.
- Do not wrap the response in Markdown code fences or add language tags (e.g., ```json). Return only raw JSON.
- Use sentence indices from the numbered full text for "evidence_sentences"
- Use table numbers from the Tables section for "evidence_tables"
- Use figure numbers from the Figures section for "evidence_figures"
"""


# ---------------------------------------------------------------------------
# Agentic screening (GREP-Agent style) prompt contracts
# ---------------------------------------------------------------------------

# NOTE:
# CAN-SR historically used JSON output for screening. The agentic plan expects
# XML-tag parsing (<answer>, <confidence>, <rationale>) so we can reuse a stable
# parsing contract across screening + critical steps.
#
# For fulltext (L2) screening, we additionally request evidence_sentences,
# evidence_tables, and evidence_figures so the UI can display clickable chips
# that scroll the PDF viewer to the relevant location.

PROMPT_XML_TEMPLATE_TA = """
You are a highly critical, helpful scientific evaluator completing an academic review.

Task:
Answer the question "{question}" for the following citation.

Citation:
{cit}

Choose EXACTLY ONE of these options (exact text):
{options}

Additional guidance:
{xtra}

Output requirement:
Return ONLY the following XML tags (no Markdown, no extra prose):
<answer>...</answer>
<confidence>...</confidence>
<rationale>...</rationale>

Field requirements:
- rationale is mandatory and must be a non-empty, concise explanation (1-4 sentences)
- connect specific facts in the citation to the selected option; do not invent evidence
- confidence is a float between 0 and 1
- be conservative; do not overestimate confidence
"""


PROMPT_XML_TEMPLATE_TA_CRITICAL = """
You are an independent critical reviewer auditing another model's screening answer.
Your task is to decide whether the original answer is the best-supported option,
not to repeat the screening task without reference to that answer.

Original question:
"{question}"

Citation:
{cit}

The first model answered:
"{screening_answer}"

Now, you MUST choose from the following forced alternatives.
Rules:
- You are NOT allowed to choose the original answer.
- AGREEMENT means the original answer is the best-supported answer. If you agree,
  choose "None of the above".
- DISAGREEMENT means one of the listed alternatives is better supported than the
  original answer. If you disagree, choose that specific alternative.
- <confidence> represents confidence in this agreement/disagreement judgment.

Forced alternatives (choose exactly one; exact text):
{options}

Additional guidance:
{xtra}

CRITICAL PROMPT ADDITIONS (SR-scoped):
{critical_additions}

Output requirement:
Return ONLY the following XML tags (no Markdown, no extra prose):
<answer>...</answer>
<confidence>...</confidence>

Confidence requirements:
- confidence is a float between 0 and 1
- be conservative; do not overestimate confidence
"""


PROMPT_XML_TEMPLATE_FULLTEXT = """
You are assisting with a scientific full-text screening task.

Task:
Evaluate the question "{question}" against the paper content provided as numbered sentences (e.g., "[0] ...", "[1] ...").

Choose EXACTLY ONE of these options (exact text):
{options}

Additional guidance:
{xtra}

Full text (numbered sentences):
{fulltext}

Tables (numbered):
{tables}

Figures (numbered; captions correspond to images provided alongside this message):
{figures}

Output requirement:
Return ONLY the following XML tags (no Markdown, no extra prose):
<answer>...</answer>
<confidence>...</confidence>
<rationale>...</rationale>
<evidence_sentences>...</evidence_sentences>
<evidence_tables>...</evidence_tables>
<evidence_figures>...</evidence_figures>

Field requirements:
- answer: the exact option string you selected (must match one of the options above)
- confidence: a float between 0 and 1; be conservative; do not overestimate confidence
- rationale: a concise explanation (1-4 sentences) of why you selected that option
- evidence_sentences: comma-separated sentence indices used as evidence (e.g. "2,5,11") or empty if none
- evidence_tables: comma-separated table numbers used (e.g. "1,3") or empty if none
- evidence_figures: comma-separated figure numbers used (e.g. "2") or empty if none
"""


PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL = """
You are an independent critical reviewer auditing another model's full-text screening answer.
Your task is to decide whether the original answer is the best-supported option,
not to repeat the screening task without reference to that answer.

Original question:
"{question}"

The first model answered:
"{screening_answer}"

Now, you MUST choose from the following forced alternatives.
Rules:
- You are NOT allowed to choose the original answer.
- AGREEMENT means the original answer is the best-supported answer. If you agree,
  choose "None of the above".
- DISAGREEMENT means one of the listed alternatives is better supported than the
  original answer. If you disagree, choose that specific alternative.
- <confidence> represents confidence in this agreement/disagreement judgment.

Forced alternatives (choose exactly one; exact text):
{options}

Additional guidance:
{xtra}

CRITICAL PROMPT ADDITIONS (SR-scoped):
{critical_additions}

Full text (numbered sentences):
{fulltext}

Tables (numbered):
{tables}

Figures (numbered; captions correspond to images provided alongside this message):
{figures}

Output requirement:
Return ONLY the following XML tags (no Markdown, no extra prose):
<answer>...</answer>
<confidence>...</confidence>

Confidence requirements:
- confidence is a float between 0 and 1
- be conservative; do not overestimate confidence
"""
