'use client'

import { useEffect, useMemo, useState } from 'react'
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
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

// The ModelInfo type is simple and only used in one place, so we define it here
// to avoid cluttering the main types file.
export interface ModelInfo {
  id: string
  name: string
  description: string
  recommended?: boolean
}

interface BackendModelCatalogItem {
  display_name?: string
  deployment?: string
  api_version?: string
}

interface ModelSelectorProps {
  selectedModel: string
  onModelChange: (model: string) => void
}

function matchesDefaultModel(args: {
  defaultChatModel?: string
  defaultChatDeployment?: string
  deployment: string
  displayName: string
}): boolean {
  const normalizedDeployment = args.deployment.trim().toLowerCase()
  const normalizedName = args.displayName.trim().toLowerCase()
  const normalizedDefaultModel = String(args.defaultChatModel || '').trim().toLowerCase()
  const normalizedDefaultDeployment = String(args.defaultChatDeployment || '').trim().toLowerCase()

  return (
    (!!normalizedDefaultDeployment && normalizedDefaultDeployment === normalizedDeployment) ||
    (!!normalizedDefaultModel && (
      normalizedDefaultModel === normalizedName ||
      normalizedDefaultModel === normalizedDeployment
    ))
  )
}

function humanizeModelIdentifier(value: string): string {
  return value
    .split('-')
    .filter(Boolean)
    .map((part) => {
      const lower = part.toLowerCase()
      if (lower === 'gpt') return 'GPT'
      if (lower === 'mini') return 'Mini'
      if (lower === 'nano') return 'Nano'
      return part.charAt(0).toUpperCase() + part.slice(1)
    })
    .join(' ')
}

function buildBackendDescription(deployment: string, apiVersion?: string): string {
  const lower = deployment.toLowerCase()
  const tier = lower.includes('nano')
    ? 'Fast lightweight GPT model'
    : lower.includes('mini')
      ? 'Compact GPT model'
      : 'Configured GPT model'

  return apiVersion ? `${tier} • ${apiVersion}` : tier
}

export function ModelSelector({
  selectedModel,
  onModelChange,
}: ModelSelectorProps) {
  const dict = useDictionary()

  const fallbackModels = useMemo<ModelInfo[]>(() => [
    {
      id: 'gpt-5.4-mini',
      name: 'GPT-5.4-Mini',
      description: dict.cansr.modelDescription1,
    },
    {
      id: 'gpt-5.4-nano',
      name: 'GPT-5.4-Nano',
      description: dict.cansr.modelDescription2,
    },
  ], [dict.cansr.modelDescription1, dict.cansr.modelDescription2])

  const descriptionOverrides = useMemo<Record<string, string>>(
    () => ({
      'gpt-5-mini': dict.cansr.modelDescription1,
      'gpt-5.4-mini': dict.cansr.modelDescription1,
      'gpt-5.4': dict.cansr.modelDescription1,
      'gpt-5.4-nano': dict.cansr.modelDescription2,
      'gpt-4.1-mini': dict.cansr.modelDescription2,
    }),
    [dict.cansr.modelDescription1, dict.cansr.modelDescription2],
  )

  const [availableModels, setAvailableModels] = useState<ModelInfo[]>(() => [
    ...fallbackModels,
  ])

  useEffect(() => {
    setAvailableModels((current) =>
      current.length > 0
        ? current.map((model) => ({
            ...model,
            description: descriptionOverrides[model.id.toLowerCase()] ?? model.description,
          }))
        : [...fallbackModels],
    )
  }, [descriptionOverrides, fallbackModels])

  useEffect(() => {
    async function loadModels() {
      try {
        const token = getAuthToken()
        const response = await fetch('/api/config', {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        })

        if (!response.ok) {
          throw new Error('Failed to fetch models')
        }

        const { config } = await response.json()
        const defaultChatModel =
          typeof config?.default_chat_model === 'string' ? config.default_chat_model : ''
        const defaultChatDeployment =
          typeof config?.default_chat_deployment === 'string'
            ? config.default_chat_deployment
            : ''

        const catalog: BackendModelCatalogItem[] = Array.isArray(config?.available_model_catalog)
          ? config.available_model_catalog
          : []

        const catalogModels = catalog
          .map((item): ModelInfo | null => {
            const deployment = String(item?.deployment || '').trim()
            if (!deployment) {
              return null
            }

            const name = String(item?.display_name || deployment).trim()
            const apiVersion = String(item?.api_version || '').trim()
            return {
              id: deployment,
              name,
              description:
                descriptionOverrides[deployment.toLowerCase()] ??
                buildBackendDescription(deployment, apiVersion),
              recommended: matchesDefaultModel({
                defaultChatModel,
                defaultChatDeployment,
                deployment,
                displayName: name,
              }),
            }
          })
          .filter((model): model is ModelInfo => Boolean(model))

        if (catalogModels.length > 0) {
          setAvailableModels(catalogModels)
          return
        }

        const deploymentIds: string[] = Array.isArray(config?.available_deployments)
          ? config.available_deployments
              .map((id: unknown) => String(id || '').trim())
              .filter(Boolean)
          : []

        if (deploymentIds.length > 0) {
          const normalizedModels = deploymentIds.map((deployment) => ({
            id: deployment,
            name: humanizeModelIdentifier(deployment),
            description:
              descriptionOverrides[deployment.toLowerCase()] ??
              buildBackendDescription(deployment),
            recommended: matchesDefaultModel({
              defaultChatModel,
              defaultChatDeployment,
              deployment,
              displayName: humanizeModelIdentifier(deployment),
            }),
          }))

          setAvailableModels(normalizedModels)
          return
        }

        const displayModels: string[] = Array.isArray(config?.available_models)
          ? config.available_models.map((id: unknown) => String(id || '').trim()).filter(Boolean)
          : []

        if (displayModels.length > 0) {
          setAvailableModels(
            displayModels.map((name) => ({
              id: name,
              name,
              description: 'Configured in backend model catalog',
              recommended: matchesDefaultModel({
                defaultChatModel,
                defaultChatDeployment,
                deployment: name,
                displayName: name,
              }),
            })),
          )
        }
      } catch (error) {
        console.error('Error fetching models:', error)
        setAvailableModels([...fallbackModels])
      }
    }

    void loadModels()
  }, [descriptionOverrides, fallbackModels])

  // Ensure selected model is valid
  useEffect(() => {
    const modelIds = availableModels.map((m) => m.id)
    const recommendedModel = availableModels.find((model) => model.recommended)?.id

    if (!selectedModel && !recommendedModel) {
      return
    }

    if (modelIds.length > 0 && !modelIds.includes(selectedModel)) {
      const defaultModel = recommendedModel || modelIds[0]
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
          {dict.cansr.models}
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
                      {dict.cansr.recommended}
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
