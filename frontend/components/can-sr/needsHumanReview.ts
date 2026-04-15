export type LatestAgentRunLite = {
  stage: 'screening' | 'critical' | string
  answer?: string | null
  confidence?: number | null
  guardrails?: any
}

export function hasGuardrailIssue(g: any): boolean {
  if (!g) return false
  try {
    const obj = typeof g === 'string' ? JSON.parse(g) : g
    if (!obj || typeof obj !== 'object') return true
    if (obj.parse_ok === false) return true
    if (obj.missing_answer) return true
    if (obj.missing_confidence) return true
    return false
  } catch {
    return true
  }
}

/**
 * Implements the source-of-truth rules from planning/agentic_implementation_plan/CLARIFICATIONS.md
 *
 * Notes:
 * - `threshold` is per-criterion and per-step (L1 and L2 can be different).
 * - Missing/invalid confidence is treated conservatively as low-confidence.
 * - Missing/empty critical answer is treated conservatively as disagreement.
 */
export function needsHumanReviewForCriterion(args: {
  threshold: number
  screening?: LatestAgentRunLite | null
  critical?: LatestAgentRunLite | null
}): {
  needsHuman: boolean
  confidentExclude: boolean
  lowConfidence: boolean
  criticalDisagrees: boolean
  guardrailIssue: boolean
} {
  const thrRaw = Number(args.threshold)
  const thr = Number.isFinite(thrRaw) ? Math.max(0, Math.min(1, thrRaw)) : 0.9

  const scr = args.screening || null
  const crit = args.critical || null

  const scrConf = Number((scr as any)?.confidence)
  const scrAns = String((scr as any)?.answer || '')

  const critAns = String((crit as any)?.answer || '').trim()
  const criticalDisagrees = !crit || critAns === '' || critAns !== 'None of the above'

  const guardrailIssue = hasGuardrailIssue((scr as any)?.guardrails) || hasGuardrailIssue((crit as any)?.guardrails)

  const lowConfidence = Number.isFinite(scrConf) ? scrConf < thr : true

  const confidentExclude =
    Number.isFinite(scrConf) &&
    scrConf >= thr &&
    scrAns.toLowerCase().includes('(exclude)') &&
    !!crit &&
    critAns === 'None of the above' &&
    !guardrailIssue

  const needsHuman = !confidentExclude && (lowConfidence || criticalDisagrees || guardrailIssue)

  return { needsHuman, confidentExclude, lowConfidence, criticalDisagrees, guardrailIssue }
}
