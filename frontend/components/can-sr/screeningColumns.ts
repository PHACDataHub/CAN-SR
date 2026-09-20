/**
 * Single source of truth for screening answer column names on the client.
 *
 * Mirrors backend/api/services/screening_columns.py. Answer columns are
 * created dynamically from the criterion question, and three rules matter:
 *
 * 1. Stage. Current columns are stage-qualified (`llm_l1_*`/`human_l1_*`).
 *    Reviews created before that change stored unqualified `llm_*`/`human_*`
 *    columns, so readers try the qualified name first and fall back.
 * 2. Length. Postgres truncates identifiers to 63 bytes, so long questions are
 *    stored under a shorter name than the raw string produces.
 * 3. Existence. Resolve against the row that actually came back rather than
 *    assuming a name is present.
 */

export type ScreeningStage = 'l1' | 'l2'

const MAX_IDENTIFIER_BYTES = 63

/** Matches snake_case(question, max_len=56) in cit_db_service.py. */
export function criterionKey(question: string): string {
  if (!question) return ''
  let value = question.trim().toLowerCase()
  value = value.replace(/[^\w]+/g, '_')
  value = value.replace(/_+/g, '_').replace(/^_+|_+$/g, '')
  if (/^\d/.test(value)) value = `c_${value}`
  return value.slice(0, 56)
}

/** Truncate to what Postgres stores, on a character boundary. */
export function truncateIdentifier(name: string): string {
  const encoder = new TextEncoder()
  if (encoder.encode(name).length <= MAX_IDENTIFIER_BYTES) return name
  let truncated = name
  while (encoder.encode(truncated).length > MAX_IDENTIFIER_BYTES) {
    truncated = truncated.slice(0, -1)
  }
  return truncated
}

/**
 * Candidate column names for one criterion, most current first.
 * Pass the result to `firstPresentColumn` against a citation row.
 */
export function screeningColumnCandidates(
  stage: ScreeningStage,
  question: string,
  source: 'human' | 'llm',
): string[] {
  const key = criterionKey(question)
  if (!key) return [source === 'llm' ? 'llm_col' : 'human_col']
  return [
    truncateIdentifier(`${source}_${stage}_${key}`),
    truncateIdentifier(`${source}_${key}`),
  ]
}

/** The first candidate the row actually carries, or undefined. */
export function firstPresentColumn(
  row: Record<string, any> | null | undefined,
  candidates: string[],
): string | undefined {
  if (!row) return undefined
  return candidates.find((candidate) =>
    Object.prototype.hasOwnProperty.call(row, candidate),
  )
}

/**
 * Read a criterion's stored answer, preferring the stage-qualified column and
 * falling back to the legacy unqualified one.
 */
export function readScreeningValue(
  row: Record<string, any> | null | undefined,
  stage: ScreeningStage,
  question: string,
  source: 'human' | 'llm',
): any {
  if (!row) return undefined
  const candidates = screeningColumnCandidates(stage, question, source)
  for (const candidate of candidates) {
    const value = row[candidate]
    if (value !== undefined && value !== null) return value
  }
  return undefined
}
