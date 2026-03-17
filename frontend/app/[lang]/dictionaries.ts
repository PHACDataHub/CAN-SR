// Might want to add server-only to dependencies
// import 'server-only'

type SupportedLocale = 'en' | 'fr'

const dictionaries: Record<SupportedLocale, () => Promise<any>> = {
  en: () => import('@/dictionaries/en.json').then((module) => module.default),
  fr: () => import('@/dictionaries/fr.json').then((module) => module.default),
}

// Fill missing translations of primary with its key by comparing with reference
// path is the recursively generated key
function fillWithKey(
  primary: any,
  reference: any,
  path: string[] = []
): any {
  // Reach end of JSON (past leaf)
  if (typeof reference !== 'object' || reference === null) {
    return primary ?? path.join('.');
  }

  // Result dictionary
  const result: any = {};

  // Iterate through list of keys from the reference dictionary
  for (const key of Object.keys(reference)) {
    // Recursive call of subproperties (if any)
    result[key] = fillWithKey(
      primary?.[key],
      reference[key],
      [...path, key]
    );
  }

  return result;
}


export const getDictionary = async (locale: 'en' | 'fr') => {
  // [lang] is a catch-all segment at runtime; guard against unexpected values
  // (e.g., when middleware/rewrites accidentally hit this layout).
  const safeLocale: SupportedLocale = locale in dictionaries ? (locale as SupportedLocale) : 'en'

  const dict = await dictionaries[safeLocale]()

  if (safeLocale === 'en') return dict

  // Compare and fill with keys if French
  const reference = await dictionaries.en()
  return fillWithKey(dict, reference)
}