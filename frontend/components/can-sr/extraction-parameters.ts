export type ExtractionParameter = {
  name: string
  description: string
  unit_instructions: string
  calculation: string
  options: string[]
  option_contexts: Record<string, string>
}

/** Normalize both canonical v2 parameters and the legacy grouped projection. */
export function flattenExtractionParameters(
  parameters: any,
): ExtractionParameter[] {
  if (!parameters || typeof parameters !== 'object') return []

  const items = Array.isArray(parameters.items) ? parameters.items : []
  if (items.length) {
    return items.flatMap((item: any) => {
      const name = typeof item?.name === 'string' ? item.name.trim() : ''
      if (!name) return []
      const options = Array.isArray(item.options)
        ? item.options
            .map((option: any) => String(option?.label ?? option ?? ''))
            .filter(Boolean)
        : []
      return [
        {
          name,
          description:
            typeof item.description === 'string' && item.description.trim()
              ? item.description.trim()
              : name,
          unit_instructions: item.unit_instructions || '',
          calculation: item.calculation || '',
          options,
          option_contexts: Object.fromEntries(
            (Array.isArray(item.options) ? item.options : [])
              .map((option: any): [string, string] => [
                String(option?.label ?? option ?? ''),
                String(option?.context || ''),
              ])
              .filter((entry: [string, string]) => entry[0]),
          ),
        },
      ]
    })
  }

  const result: ExtractionParameter[] = []
  const categories = Array.isArray(parameters.categories)
    ? parameters.categories
    : []
  const grouped = Array.isArray(parameters.possible_parameters)
    ? parameters.possible_parameters
    : []
  categories.forEach((_category: unknown, index: number) => {
    const descriptions = Array.isArray(parameters.descriptions?.[index])
      ? parameters.descriptions[index]
      : []
    ;(Array.isArray(grouped[index]) ? grouped[index] : []).forEach(
      (raw: any, itemIndex: number) => {
        const name =
          typeof raw === 'string'
            ? raw.trim()
            : Array.isArray(raw)
              ? String(raw[0] || '').trim()
              : String(raw || '').trim()
        if (!name) return
        const description =
          typeof descriptions[itemIndex] === 'string'
            ? descriptions[itemIndex].replace(/<\/?desc>/g, '')
            : ''
        result.push({
          name,
          description: description || name,
          unit_instructions: '',
          calculation: '',
          options: [],
          option_contexts: {},
        })
      },
    )
  })
  return result
}
