import { useState, useEffect, useCallback } from 'react'
import type { Settings } from '@/components/chat/types'

// Default Health Canada system prompt
export const DEFAULT_SYSTEM_PROMPT = `You are an AI assistant for Health Canada. Your role is to help users answer scientific questions based on official scientific documents, research studies, and regulatory assessments.

Answer the question using the following context between XML tags <context></context>:
<context>{context}</context>
Always include the chunk number for each chunk you use in the response.
Use square brackets to reference the source, for example [52].
Don't combine citations, list each product separately, for example [27][51]

Guidelines:
- Use only the provided context documents to answer questions
- Focus on scientific accuracy and evidence-based responses
- If information is not available, clearly state that
- Maintain a professional, helpful tone appropriate for scientific communications
- For sensitive information, remind users to follow proper security protocols`

// Default query rewriter prompts for each mode
export const DEFAULT_QUERY_REWRITER_PROMPTS = {
  simple: `Here are examples to guide you:

Example 1:
Verbose Query: What is the acceptable daily intake of glyphosate for humans?
Simplified Query: glyphosate acceptable daily intake humans

Example 2:
Verbose Query: What are the reproductive parameters evaluated in OECD TG 408?
Simplified Query: reproductive parameters OECD TG 408

Example 3:
Verbose Query: Tell me about malathion and glyphosate monograph differences
Simplified Query: malathion glyphosate monograph differences

Example 4:
Verbose Query: Tell me what studies say about aquatic ecotoxicology of triticonazole
Simplified Query: triticonazole aquatic ecotoxicology studies

Example 5:
Verbose Query: How does Health Canada evaluate carcinogenicity in pesticide assessments?
Simplified Query: Health Canada carcinogenicity evaluation pesticide assessment

Example 6:
Verbose Query: What are the latest PMRA decisions on neonicotinoid registrations?
Simplified Query: PMRA neonicotinoid registration decisions

Your task is to process the following query:

{question}

Return only the simplified query. If the query is already sufficiently concise, return it exactly as it is.
Do not include any additional text or labels such as "Original Query" or "Simplified Query"—only output the simplified query itself.`,

  with_context: `Transform the query for comprehensive scientific document retrieval. Focus on terms that will retrieve relevant regulatory and research documents.

Here are examples to guide you:

Example 1:
Verbose Query: What are the environmental effects of glyphosate on aquatic organisms?
Simplified Query: glyphosate environmental effects aquatic organisms toxicity

Example 2:
Verbose Query: Compare the risk assessment methodologies for malathion and glyphosate
Simplified Query: malathion glyphosate risk assessment methodology comparison

Example 3:
Verbose Query: What does the latest research say about neonicotinoid impacts on bee populations?
Simplified Query: neonicotinoid bee population impact research studies

Example 4:
Verbose Query: How does Health Canada's PMRA evaluate chronic dietary exposure to pesticides?
Simplified Query: Health Canada PMRA chronic dietary exposure pesticide evaluation

Example 5:
Verbose Query: What are the requirements for reproductive toxicity studies under OECD guidelines?
Simplified Query: reproductive toxicity studies OECD guidelines requirements

Your task is to process the following query:

{question}

Return only the simplified query optimized for document retrieval. Focus on scientific and regulatory terminology that will match relevant documents.`,

  filtered: `Transform the query for public-appropriate scientific document retrieval, focusing on published research and regulatory assessments.

Here are examples to guide you:

Example 1:
Verbose Query: What internal procedures does PMRA use for pesticide evaluation?
Simplified Query: PMRA pesticide evaluation procedures public guidelines

Example 2:
Verbose Query: Show me confidential toxicity data for glyphosate
Simplified Query: glyphosate toxicity studies published research regulatory assessment

Example 3:
Verbose Query: What does the latest research say about neonicotinoid safety?
Simplified Query: neonicotinoid safety research studies published assessment

Example 4:
Verbose Query: Internal Health Canada risk assessment protocols
Simplified Query: Health Canada risk assessment protocols public guidelines

Example 5:
Verbose Query: Confidential industry studies on pesticide residues
Simplified Query: pesticide residues studies published research regulatory data

Your task is to process the following query:

{question}

Return only the simplified query optimized for public-appropriate document retrieval. Focus on published research, regulatory assessments, and publicly available information.`,
}

// Default query rewriter prompt for 'with_context' mode (for backward compatibility)
const DEFAULT_QUERY_REWRITER_PROMPT =
  DEFAULT_QUERY_REWRITER_PROMPTS.with_context

// Default settings
const DEFAULT_SETTINGS: Settings = {
  // Core chat parameters
  temperature: 0.7,
  max_tokens: 1500,
  top_p: 1.0,

  // RAG parameters
  search_type: 'hybrid',
  search_base_knowledge: true,
  search_user_knowledge: true,
  top_k: 5,
  hybrid_weight: 0.5,
  system_prompt: DEFAULT_SYSTEM_PROMPT,

  // Query Rewriter parameters
  enable_query_rewriting: true,
  query_rewrite_mode: 'with_context',
  query_rewriter_prompt: DEFAULT_QUERY_REWRITER_PROMPT,

  // UI/Legacy parameters (for backward compatibility)
  use_rag: true,
  use_reranker: true,
  moderationfilter: false,
  onlyusecontext: false,
  embedding_model: 'bge-m3',
  chunking_method: 'hybrid',
}

const STORAGE_KEY = 'science-gpt-settings'

interface UseSettingsReturn {
  settings: Settings
  updateSetting: <K extends keyof Settings>(key: K, value: Settings[K]) => void
  resetSettings: () => void
  isLoading: boolean
  saveStatus: 'idle' | 'saving' | 'saved'
}

export function useSettings(): UseSettingsReturn {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS)
  const [isLoading, setIsLoading] = useState(true)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>(
    'idle',
  )
  const [saveTimeout, setSaveTimeout] = useState<NodeJS.Timeout | null>(null)

  useEffect(() => {
    try {
      const savedSettings = localStorage.getItem(STORAGE_KEY)
      if (savedSettings) {
        const parsed = JSON.parse(savedSettings)
        let finalSettings = { ...DEFAULT_SETTINGS, ...parsed }

        // Migration: Initialize new knowledge base selection settings if they don't exist
        if (
          finalSettings.search_base_knowledge === undefined ||
          finalSettings.search_user_knowledge === undefined
        ) {
          // Set defaults based on existing search_type if available
          if (finalSettings.search_type === 'base_only') {
            finalSettings.search_base_knowledge = true
            finalSettings.search_user_knowledge = false
          } else if (finalSettings.search_type === 'user_only') {
            finalSettings.search_base_knowledge = false
            finalSettings.search_user_knowledge = true
          } else {
            // Default to both for hybrid or any other case
            finalSettings.search_base_knowledge = true
            finalSettings.search_user_knowledge = true
            finalSettings.search_type = 'hybrid'
          }
        }

        setSettings(finalSettings)
      } else {
        setSettings(DEFAULT_SETTINGS)
      }
    } catch (error) {
      console.error('Error loading settings:', error)
      setSettings(DEFAULT_SETTINGS)
    } finally {
      setIsLoading(false)
    }
  }, [])

  const saveSettings = useCallback((newSettings: Settings) => {
    try {
      setSaveStatus('saving')
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newSettings))
      setSaveStatus('saved')

      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch (error) {
      console.error('Error saving settings:', error)
      setSaveStatus('idle')
    }
  }, [])

  const updateSetting = useCallback(
    <K extends keyof Settings>(key: K, value: Settings[K]) => {
      setSettings((prevSettings) => {
        let newSettings = { ...prevSettings, [key]: value }

        // Auto-update search_type based on knowledge base selections
        if (
          key === 'search_base_knowledge' ||
          key === 'search_user_knowledge'
        ) {
          const baseSelected =
            key === 'search_base_knowledge'
              ? (value as boolean)
              : newSettings.search_base_knowledge
          const userSelected =
            key === 'search_user_knowledge'
              ? (value as boolean)
              : newSettings.search_user_knowledge

          if (baseSelected && userSelected) {
            newSettings.search_type = 'hybrid'
          } else if (baseSelected && !userSelected) {
            newSettings.search_type = 'base_only'
          } else if (!baseSelected && userSelected) {
            newSettings.search_type = 'user_only'
          } else {
            // If neither is selected, default to hybrid and select both
            newSettings.search_type = 'hybrid'
            newSettings.search_base_knowledge = true
            newSettings.search_user_knowledge = true
          }
        }

        // Clear any existing timeout
        if (saveTimeout) {
          clearTimeout(saveTimeout)
        }

        // Set up new save timeout
        const timeout = setTimeout(() => {
          saveSettings(newSettings)
        }, 500)

        setSaveTimeout(timeout)

        return newSettings
      })
    },
    [saveTimeout, saveSettings],
  )

  const resetSettings = useCallback(() => {
    setSettings(DEFAULT_SETTINGS)
    try {
      localStorage.removeItem(STORAGE_KEY)
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch (error) {
      console.error('Error resetting settings:', error)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (saveTimeout) {
        clearTimeout(saveTimeout)
      }
    }
  }, [saveTimeout])

  return {
    settings,
    updateSetting,
    resetSettings,
    isLoading,
    saveStatus,
  }
}
