import type { CriteriaConfig } from './criteria-types'

export default function CriteriaPreview({ criteria, labels }: { criteria: CriteriaConfig; labels: Record<string, string> }) {
  const textParameters = criteria.parameters.filter((item) => item.type === 'text').length
  const singleParameters = criteria.parameters.filter((item) => item.type === 'selection' && item.selection_mode === 'single').length
  const multipleParameters = criteria.parameters.filter((item) => item.type === 'selection' && item.selection_mode === 'multiple').length
  const conditionalItems = [...criteria.l1, ...criteria.l2, ...criteria.parameters].filter((item) => item.trigger.all.length > 0).length
  return <details className="rounded-lg border border-gray-200 bg-gray-50 p-4">
    <summary className="cursor-pointer font-semibold">{labels.preview}</summary>
    <p className="mt-2 text-sm text-gray-600">{labels.previewDescription}</p>
    <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
      <div><dt className="font-medium">{labels.l1}</dt><dd>{criteria.l1.length} {labels.questionsCount}</dd></div>
      <div><dt className="font-medium">{labels.l2}</dt><dd>{criteria.l2.length} {labels.questionsCount}</dd></div>
      <div><dt className="font-medium">{labels.parameters}</dt><dd>{criteria.parameters.length} {labels.parametersCount}</dd></div>
      <div><dt className="font-medium">{labels.conditionalItems}</dt><dd>{conditionalItems}</dd></div>
    </dl>
    <p className="mt-3 text-sm">{labels.parameterModes}: {textParameters} {labels.freeText}, {singleParameters} {labels.singleSelection}, {multipleParameters} {labels.multipleSelection}</p>
    <p className="mt-1 text-sm">{labels.citationFields}: {criteria.citation_fields.l1_include.join(', ') || labels.none}; {labels.doiField}: {criteria.citation_fields.doi || labels.none}</p>
  </details>
}
