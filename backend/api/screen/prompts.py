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