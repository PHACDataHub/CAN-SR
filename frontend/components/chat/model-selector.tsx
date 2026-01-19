'use client'

import { useState, useEffect } from 'react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Cpu } from 'lucide-react'
import { getAuthToken } from '@/lib/auth'

// The ModelInfo type is simple and only used in one place, so we define it here
// to avoid cluttering the main types file.
export interface ModelInfo {
  id: string
  name: string
  description: string
  recommended?: boolean
}

interface ModelSelectorProps {
  selectedModel: string
  onModelChange: (model: string) => void
}

// Azure OpenAI model configurations with descriptions
const MODEL_INFO: Record<string, ModelInfo> = {
  'gpt-4o': {
    id: 'gpt-4o',
    name: 'GPT-4o',
    description: 'Great for most tasks',
    recommended: true,
  },
  'gpt-4o-mini': {
    id: 'gpt-4o-mini',
    name: 'GPT-4o mini',
    description: 'Faster for everyday tasks',
  },
  'gpt-4.1-mini': {
    id: 'gpt-4.1-mini',
    name: 'GPT-4.1 mini',
    description: 'Latest mini model, fastest at advanced reasoning',
  },
}

export function ModelSelector({
  selectedModel,
  onModelChange,
}: ModelSelectorProps) {
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([
    MODEL_INFO['gpt-4o'],
    MODEL_INFO['gpt-4o-mini'],
    MODEL_INFO['gpt-4.1-mini'],
  ])

  useEffect(() => {
    async function loadModels() {
      try {
        const token = getAuthToken()
        const response = await fetch('/api/chat/models', {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        })

        if (!response.ok) {
          throw new Error('Failed to fetch models')
        }

        const data = await response.json()
        const modelIds = data.available_models || []

        // Filter to only show models we have info for (your configured Azure OpenAI models)
        const filteredModels = modelIds
          .filter((id: string) => MODEL_INFO[id])
          .map((id: string) => MODEL_INFO[id])

        if (filteredModels.length > 0) {
          setAvailableModels(filteredModels)
        }
      } catch (error) {
        console.error('Error fetching models:', error)
        // Keep using the default models
      }
    }

    const timeoutId = setTimeout(loadModels, 100)
    return () => clearTimeout(timeoutId)
  }, [])

  // Ensure selected model is valid
  useEffect(() => {
    const modelIds = availableModels.map((m) => m.id)
    if (modelIds.length > 0 && !modelIds.includes(selectedModel)) {
      const defaultModel = modelIds.includes('gpt-4o') ? 'gpt-4o' : modelIds[0]
      onModelChange(defaultModel)
    }
  }, [availableModels, selectedModel, onModelChange])

  const selectedModelInfo = availableModels.find((m) => m.id === selectedModel)

  return (
    <Select value={selectedModel} onValueChange={onModelChange}>
      <SelectTrigger className="h-9 w-auto gap-2 border-gray-200 bg-white font-medium shadow-sm transition-all hover:border-gray-300 hover:bg-gray-50 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20">
        <Cpu className="h-4 w-4 text-gray-600" />
        <SelectValue placeholder="Select a model">
          {selectedModelInfo?.name || selectedModel}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="w-72 border-gray-200 bg-white shadow-lg">
        <div className="border-b border-gray-100 px-3 py-2 text-xs font-medium tracking-wide text-gray-500 uppercase">
          Models
        </div>
        {availableModels.map((model) => (
          <SelectItem
            key={model.id}
            value={model.id}
            className={`cursor-pointer border-0 px-3 py-3 transition-colors duration-150 focus:outline-none ${
              selectedModel === model.id
                ? 'bg-white data-[highlighted]:bg-white'
                : 'hover:bg-gray-50 focus:bg-gray-50 data-[highlighted]:bg-gray-50'
            } data-[state=checked]:bg-white`}
          >
            <div className="flex w-full items-center justify-between">
              <div className="flex flex-col items-start">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">
                    {model.name}
                  </span>
                  {model.recommended && (
                    <Badge className="border-0 bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 hover:bg-blue-100">
                      Recommended
                    </Badge>
                  )}
                </div>
                <span className="mt-1 text-sm text-gray-500">
                  {model.description}
                </span>
              </div>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
