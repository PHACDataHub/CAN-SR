'use client'

import React from 'react'

export type CitationFields = {
  title?: string | null
  abstract?: string | null
  doi?: string | null
  l1_include?: string[]
}

export function resolveConfiguredValue(
  row: Record<string, any> | null | undefined,
  header?: string | null,
) {
  if (!row || !header) return undefined
  if (Object.prototype.hasOwnProperty.call(row, header)) return row[header]
  const normalize = (value: string) =>
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
  const key = normalize(header)
  const matches = Object.keys(row).filter(
    (candidate) => normalize(candidate) === key,
  )
  return matches.length === 1 ? row[matches[0]] : undefined
}

function normalizeScreeningKey(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_')
}

function legacyScreeningAnswerColumn(
  question: string,
  prefix: 'human' | 'llm',
) {
  const core = normalizeScreeningKey(question)
  if (!core) return `${prefix}_col`
  return `${prefix}_${core}`.slice(0, 60)
}

function screeningAnswerCandidateHeaders(
  question: string,
  stage: 'l1' | 'l2',
  prefix: 'human' | 'llm',
) {
  const headers = [screeningAnswerColumn(question, prefix, stage)]
  if (stage === 'l2') {
    headers.push(screeningAnswerColumn(question, prefix, 'l1'))
  }
  headers.push(legacyScreeningAnswerColumn(question, prefix))
  return headers
}

export function screeningAnswerColumn(
  question: string,
  prefix: 'human' | 'llm',
  stage: 'l1' | 'l2',
) {
  const core = normalizeScreeningKey(question).slice(0, 56)
  if (!core) return `${prefix}_col`
  return `${prefix}_${stage}_${core}`.slice(0, 63)
}

export function resolveScreeningAnswerValue(
  row: Record<string, any> | null | undefined,
  question: string,
  stage: 'l1' | 'l2',
  prefix: 'human' | 'llm',
  fallbackHeaders: Array<string | null | undefined> = [],
) {
  const headers = [
    ...screeningAnswerCandidateHeaders(question, stage, prefix),
    ...fallbackHeaders,
  ].filter(
    (header): header is string =>
      typeof header === 'string' && header.trim().length > 0,
  )

  for (const header of headers) {
    const value = resolveConfiguredValue(row, header)
    if (value !== undefined) return value
  }

  return undefined
}

export function extractHumanAnswer(value: any): string {
  if (value === undefined || value === null) return ''
  if (typeof value === 'object')
    return String(value.selected ?? value.value ?? '')
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return typeof parsed === 'object'
        ? String(parsed?.selected ?? parsed?.value ?? '')
        : value
    } catch {
      return value.trim()
    }
  }
  return String(value)
}

/** Return the answer shown in a screening control, without changing persistence. */
export function resolveDisplayedAnswer(humanValue: any, aiValue: any): string {
  const human = extractHumanAnswer(humanValue).trim()
  if (human) return human
  return extractHumanAnswer(aiValue).trim()
}

export function humanAnswerStatus(
  row: Record<string, any> | null | undefined,
  answerColumn: string | null | undefined,
  options: string[],
): 'unconfigured' | 'missing' | 'blank' | 'matched' | 'unmatched' {
  return humanAnswerStatusForColumns(row, [answerColumn], options)
}

export function humanAnswerStatusForColumns(
  row: Record<string, any> | null | undefined,
  answerColumns: Array<string | null | undefined>,
  options: string[],
): 'unconfigured' | 'missing' | 'blank' | 'matched' | 'unmatched' {
  const headers = answerColumns.filter(
    (header): header is string =>
      typeof header === 'string' && header.trim().length > 0,
  )
  if (!headers.length) return 'unconfigured'

  let raw: any = undefined
  for (const header of headers) {
    raw = resolveConfiguredValue(row, header)
    if (raw !== undefined) break
  }
  if (raw === undefined) return 'missing'
  const answer = extractHumanAnswer(raw).trim()
  if (!answer) return 'blank'
  if (!options.length) return 'matched'
  const normalized = answer.toLowerCase().replace(/\s+/g, ' ')
  return options.some(
    (option) => option.trim().toLowerCase().replace(/\s+/g, ' ') === normalized,
  )
    ? 'matched'
    : 'unmatched'
}

export function resolveConfiguredAnswerWarning(
  row: Record<string, any> | null | undefined,
  answerColumn: string | null | undefined,
  configuredAnswerColumn: string | null | undefined,
  options: string[],
): {
  column: string
  status: 'missing' | 'blank' | 'unmatched'
} | null {
  if (
    !configuredAnswerColumn ||
    configuredAnswerColumn.trim().length === 0 ||
    configuredAnswerColumn === answerColumn
  ) {
    return null
  }

  const status = humanAnswerStatus(row, configuredAnswerColumn, options)
  if (
    status === 'unconfigured' ||
    status === 'matched'
  ) {
    return null
  }

  return {
    column: configuredAnswerColumn,
    status,
  }
}

export function ScreeningCitationContext({
  citation,
  fields,
  showTitleAbstract = true,
}: {
  citation: Record<string, any>
  fields?: CitationFields | null
  showTitleAbstract?: boolean
}) {
  const title =
    resolveConfiguredValue(citation, fields?.title) ?? citation.title
  const abstract =
    resolveConfiguredValue(citation, fields?.abstract) ?? citation.abstract
  const normalizeHeader = (header: string) =>
    header
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
  const excluded = new Set(
    [fields?.title, fields?.abstract]
      .filter(Boolean)
      .map((header) => normalizeHeader(String(header))),
  )
  const other = (fields?.l1_include || [])
    .filter((header) => !excluded.has(normalizeHeader(header)))
    .map((header) => ({
      header,
      value: resolveConfiguredValue(citation, header),
    }))
    .filter(
      ({ value }) =>
        value !== undefined && value !== null && String(value).trim() !== '',
    )

  return (
    <div className="space-y-3">
      {showTitleAbstract ? (
        <>
          <div>
            <p className="text-xs text-gray-600">Citation #{citation.id}</p>
            <h2 className="text-lg font-semibold text-gray-900">
              {String(title || '')}
            </h2>
          </div>
          <div className="rounded-md border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-medium text-gray-800">Abstract</h3>
            <p className="mt-2 text-sm whitespace-pre-wrap text-gray-800">
              {String(abstract || 'No abstract available')}
            </p>
          </div>
        </>
      ) : null}
      {other.length > 0 && (
        <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
          <h3 className="text-sm font-medium text-gray-800">
            Other citation fields
          </h3>
          <dl className="mt-2 space-y-1 text-sm text-gray-700">
            {other.map(({ header, value }) => (
              <div key={header}>
                <dt className="inline font-medium">{header}: </dt>
                <dd className="inline whitespace-pre-wrap">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}
