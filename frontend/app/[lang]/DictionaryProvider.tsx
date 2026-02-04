'use client'

import { createContext, useContext, ReactNode } from 'react'

type Dictionary = Record<string, Record<string, string>>

const DictionaryContext = createContext<Dictionary | null>(null)

export function DictionaryProvider({
  dictionary,
  children,
}: {
  dictionary: Dictionary
  children: ReactNode
}) {
  return (
    <DictionaryContext.Provider value={dictionary}>
      {children}
    </DictionaryContext.Provider>
  )
}

export function useDictionary() {
  const dictionary = useContext(DictionaryContext)
  if (!dictionary) {
    throw new Error('useDictionary must be used within a DictionaryProvider')
  }
  return dictionary
}
