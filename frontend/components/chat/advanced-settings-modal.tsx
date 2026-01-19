'use client'

import { useState, useEffect, useCallback } from 'react'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { SimpleTooltip } from '@/components/ui/tooltip'
import { HelpCircle, RotateCcw } from 'lucide-react'
import { MilvusViewer } from './milvus-viewer'
import type { Settings } from './types'
import {
  DEFAULT_QUERY_REWRITER_PROMPTS,
  DEFAULT_SYSTEM_PROMPT,
} from '@/hooks/use-settings'

interface AdvancedSettingsModalProps {
  isOpen: boolean
  onOpenChange: (isOpen: boolean) => void
  settings: Settings
  onSettingsChange: <K extends keyof Settings>(
    key: K,
    value: Settings[K],
  ) => void
  lastQueryMetadata?: any
}

export function AdvancedSettingsModal({
  isOpen,
  onOpenChange,
  settings,
  onSettingsChange,
  lastQueryMetadata,
}: AdvancedSettingsModalProps) {
  const [saveAnimation, setSaveAnimation] = useState(false)

  const updateSetting = useCallback(
    <K extends keyof Settings>(key: K, value: Settings[K]) => {
      onSettingsChange(key, value)

      // Trigger save animation after the debounce delay
      setTimeout(() => {
        setSaveAnimation(true)
        // Reset animation after 1.8 seconds for optimal user feedback
        setTimeout(() => setSaveAnimation(false), 1800)
      }, 600) // Slightly longer than the 500ms debounce to ensure save is complete
    },
    [onSettingsChange],
  )

  // Handle query rewrite mode change and auto-populate prompt
  const handleQueryRewriteModeChange = (
    mode: 'simple' | 'with_context' | 'filtered',
  ) => {
    const newModeDefaultPrompt = DEFAULT_QUERY_REWRITER_PROMPTS[mode]

    // Update both mode and prompt together to avoid timing issues
    updateSetting('query_rewrite_mode', mode)
    updateSetting('query_rewriter_prompt', newModeDefaultPrompt)
  }

  // Initialize settings when component mounts or when mode changes
  useEffect(() => {
    // Initialize enable_query_rewriting if undefined
    if (settings.enable_query_rewriting === undefined) {
      updateSetting('enable_query_rewriting', true)
    }
  }, [settings.enable_query_rewriting, updateSetting])

  // Ensure prompt is set for the current mode
  useEffect(() => {
    if (!settings.query_rewriter_prompt && settings.query_rewrite_mode) {
      const currentModeDefaultPrompt =
        DEFAULT_QUERY_REWRITER_PROMPTS[settings.query_rewrite_mode]
      if (currentModeDefaultPrompt) {
        updateSetting('query_rewriter_prompt', currentModeDefaultPrompt)
      }
    }
  }, [
    settings.query_rewrite_mode,
    settings.query_rewriter_prompt,
    updateSetting,
  ])

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[700px] max-h-[700px] w-[500px] max-w-[500px] flex-col">
        <DialogHeader className="pb-3">
          <DialogTitle className="text-lg font-medium">
            Advanced Settings
          </DialogTitle>
          <DialogDescription className="text-sm text-gray-500">
            Fine-tune AI behavior
          </DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-hidden">
          <Tabs
            defaultValue="retrieval"
            className="flex h-full w-full flex-col"
          >
            <TabsList className="mb-4 grid h-9 w-full grid-cols-4 rounded-lg bg-gray-100 p-1">
              <TabsTrigger
                value="retrieval"
                className="rounded-md text-sm font-medium transition-all duration-200 data-[state=active]:bg-white data-[state=active]:shadow-sm"
              >
                Retrieval
              </TabsTrigger>
              <TabsTrigger
                value="generation"
                className="rounded-md text-sm font-medium transition-all duration-200 data-[state=active]:bg-white data-[state=active]:shadow-sm"
              >
                Generation
              </TabsTrigger>
              <TabsTrigger
                value="query"
                className="rounded-md text-sm font-medium transition-all duration-200 data-[state=active]:bg-white data-[state=active]:shadow-sm"
              >
                Query
              </TabsTrigger>
              <TabsTrigger
                value="database"
                className="rounded-md text-sm font-medium transition-all duration-200 data-[state=active]:bg-white data-[state=active]:shadow-sm"
              >
                Database
              </TabsTrigger>
            </TabsList>

            <TabsContent
              value="retrieval"
              className="hide-scrollbar flex-1 space-y-3 overflow-y-auto p-1"
            >
              {/* RAG Toggle */}
              <div className="flex items-center justify-between py-1">
                <div className="flex items-center gap-1">
                  <Label htmlFor="use-rag" className="text-xs font-medium">
                    Use RAG
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Enable Retrieval Augmented Generation to search through
                        your documents for relevant context
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <Switch
                  id="use-rag"
                  checked={settings.use_rag}
                  onCheckedChange={(val) => updateSetting('use_rag', val)}
                />
              </div>

              {/* Top-K */}
              <div
                className={
                  !settings.use_rag ? 'pointer-events-none opacity-50' : ''
                }
              >
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Top-K ({settings.top_k})
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Number of relevant document chunks to retrieve for
                        context (1-10)
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <div className="px-1 py-2">
                  <Slider
                    value={[settings.top_k]}
                    onValueChange={([value]) => {
                      if (!settings.use_rag) return
                      updateSetting('top_k', value)
                    }}
                    max={10}
                    min={1}
                    step={1}
                    disabled={!settings.use_rag}
                    className="w-full"
                  />
                </div>
                <div className="mt-1 flex justify-between text-xs text-gray-400">
                  <span>Few chunks</span>
                  <span>More chunks</span>
                </div>
              </div>

              {/* Hybrid Search Weight */}
              <div
                className={
                  !settings.use_rag ? 'pointer-events-none opacity-50' : ''
                }
              >
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Hybrid Weight ({settings.hybrid_weight.toFixed(1)})
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Balance between semantic search (0.0) and keyword search
                        (1.0). 0.5 is balanced. Applies to all searched
                        collections.
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <div className="px-1 py-2">
                  <Slider
                    value={[settings.hybrid_weight]}
                    onValueChange={(values) => {
                      if (!settings.use_rag) return
                      const val = values[0]
                      updateSetting('hybrid_weight', val)
                    }}
                    max={1}
                    min={0}
                    step={0.1}
                    disabled={!settings.use_rag}
                    className="w-full"
                  />
                </div>
                <div className="mt-1 flex justify-between text-xs text-gray-400">
                  <span>Semantic</span>
                  <span>Keyword</span>
                </div>
              </div>

              {/* Reranker */}
              <div
                className={
                  !settings.use_rag ? 'pointer-events-none opacity-50' : ''
                }
              >
                <div className="flex items-center justify-between py-1">
                  <div className="flex items-center gap-1">
                    <Label
                      htmlFor="use-reranker"
                      className="text-xs font-medium"
                    >
                      Reranker
                    </Label>
                    <SimpleTooltip
                      content={
                        <p>
                          Use BGE reranker to improve search result relevance by
                          reordering results
                        </p>
                      }
                    >
                      <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                    </SimpleTooltip>
                  </div>
                  <Switch
                    id="use-reranker"
                    checked={settings.use_reranker}
                    onCheckedChange={(val) =>
                      updateSetting('use_reranker', val)
                    }
                    disabled={!settings.use_rag}
                  />
                </div>
              </div>

              {/* Knowledge Base Selection */}
              <div
                className={
                  !settings.use_rag ? 'pointer-events-none opacity-50' : ''
                }
              >
                <div className="mb-2">
                  <div className="flex items-center gap-1">
                    <Label className="text-xs font-medium">
                      Knowledge Bases
                    </Label>
                    <SimpleTooltip
                      content={
                        <p>
                          Select which knowledge bases to search. You must
                          choose at least one knowledge base.
                        </p>
                      }
                    >
                      <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                    </SimpleTooltip>
                  </div>
                  <div className="mt-1 text-xs text-amber-600">
                    * Must select at least one knowledge base
                  </div>
                </div>

                {/* Knowledge Base Selection Buttons */}
                <div className="flex gap-2 rounded-lg border border-gray-200 bg-gray-50 p-1">
                  {/* Base Knowledge Button */}
                  <button
                    type="button"
                    onClick={() =>
                      updateSetting(
                        'search_base_knowledge',
                        !settings.search_base_knowledge,
                      )
                    }
                    disabled={!settings.use_rag}
                    className={`flex-1 rounded-md px-3 py-2 text-xs font-medium transition-all duration-200 ${
                      settings.search_base_knowledge
                        ? 'border border-blue-600 bg-blue-500 text-white shadow-sm'
                        : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-100'
                    } ${!settings.use_rag ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                  >
                    Base Knowledge
                  </button>

                  {/* User Documents Button */}
                  <button
                    type="button"
                    onClick={() =>
                      updateSetting(
                        'search_user_knowledge',
                        !settings.search_user_knowledge,
                      )
                    }
                    disabled={!settings.use_rag}
                    className={`flex-1 rounded-md px-3 py-2 text-xs font-medium transition-all duration-200 ${
                      settings.search_user_knowledge
                        ? 'border border-blue-600 bg-blue-500 text-white shadow-sm'
                        : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-100'
                    } ${!settings.use_rag ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
                  >
                    Your Documents
                  </button>
                </div>

                {/* Search Mode Indicator */}
                <div className="mt-2 text-center">
                  <div className="text-xs text-gray-500">
                    {settings.search_type === 'hybrid' &&
                      '🔍 Searching both knowledge bases'}
                    {settings.search_type === 'base_only' &&
                      '📚 Searching base knowledge only'}
                    {settings.search_type === 'user_only' &&
                      '📄 Searching your documents only'}
                  </div>
                </div>
              </div>
            </TabsContent>

            <TabsContent
              value="generation"
              className="relative flex-1 space-y-3 overflow-y-auto p-1"
            >
              {/* Temperature */}
              <div>
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Temperature ({settings.temperature.toFixed(1)})
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Controls creativity and randomness. Lower = more
                        focused, Higher = more creative
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <Slider
                  value={[settings.temperature]}
                  onValueChange={([value]) =>
                    updateSetting('temperature', value)
                  }
                  max={1}
                  min={0}
                  step={0.1}
                  className="w-full"
                />
                <div className="mt-1 flex justify-between text-xs text-gray-400">
                  <span>Focused</span>
                  <span>Creative</span>
                </div>
              </div>

              {/* Top P */}
              <div>
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Top P ({settings.top_p.toFixed(1)})
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Nucleus sampling. Controls diversity by limiting token
                        selection to top probability mass
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <Slider
                  value={[settings.top_p]}
                  onValueChange={([value]) => updateSetting('top_p', value)}
                  max={1}
                  min={0}
                  step={0.1}
                  className="w-full"
                />
                <div className="mt-1 flex justify-between text-xs text-gray-400">
                  <span>Restrictive</span>
                  <span>Diverse</span>
                </div>
              </div>

              {/* Max Tokens */}
              <div>
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Max Tokens ({settings.max_tokens})
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Maximum number of tokens the model can generate in
                        response (50-4000)
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <Slider
                  value={[settings.max_tokens]}
                  onValueChange={([value]) =>
                    updateSetting('max_tokens', value)
                  }
                  max={4000}
                  min={50}
                  step={50}
                  className="w-full"
                />
                <div className="mt-1 flex justify-between text-xs text-gray-400">
                  <span>Brief</span>
                  <span>Detailed</span>
                </div>
              </div>

              {/* System Prompt */}
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    <Label className="text-xs font-medium">System Prompt</Label>
                    <SimpleTooltip
                      content={
                        <p>
                          Customize the AI&apos;s behavior and response style.
                          Changes are automatically saved.
                        </p>
                      }
                    >
                      <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                    </SimpleTooltip>
                  </div>
                  {settings.system_prompt &&
                    settings.system_prompt !== DEFAULT_SYSTEM_PROMPT && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          updateSetting('system_prompt', DEFAULT_SYSTEM_PROMPT)
                        }
                        className="h-6 px-2 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                      >
                        <RotateCcw className="mr-1 h-3 w-3" />
                        Reset
                      </Button>
                    )}
                </div>
                <textarea
                  placeholder="Feel free to customize the system prompt..."
                  value={settings.system_prompt || ''}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                    updateSetting('system_prompt', e.target.value || undefined)
                  }
                  className="h-[140px] w-full resize-none rounded-lg border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 transition-all duration-200 placeholder:text-gray-400 hover:border-gray-300 focus:border-blue-500 focus:bg-blue-50/30 focus:shadow-sm focus:ring-0 focus:outline-none"
                  style={{
                    overflowY: 'auto',
                    overflowX: 'hidden',
                    scrollbarWidth: 'thin',
                    scrollbarColor: '#cbd5e1 #f1f5f9',
                  }}
                />
                <div className="mt-1 text-xs text-gray-500">
                  Default Health Canada prompt active
                </div>
              </div>

              {/* Spacer for better scrolling */}
              <div className="h-4"></div>
            </TabsContent>

            <TabsContent
              value="query"
              className="hide-scrollbar flex-1 space-y-3 overflow-y-auto p-1"
            >
              {/* Enable Query Rewriting */}
              <div className="flex items-center justify-between py-1">
                <div className="flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Enable Query Rewriting
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Automatically optimize queries for better search results
                        by extracting key scientific terms and removing verbose
                        language.
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <Switch
                  checked={settings.enable_query_rewriting}
                  onCheckedChange={(checked) =>
                    updateSetting('enable_query_rewriting', checked)
                  }
                />
              </div>

              {/* Query Rewriting Results */}
              <div className="rounded-lg border border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50 p-4 shadow-sm">
                <div className="mb-3 flex items-center gap-2">
                  <Label className="text-sm font-semibold text-blue-900">
                    Query Rewriting Result
                  </Label>
                  {lastQueryMetadata && (
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
                        lastQueryMetadata.query_was_rewritten
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {lastQueryMetadata.query_was_rewritten
                        ? 'Rewritten'
                        : 'Not Rewritten'}
                    </span>
                  )}
                  <SimpleTooltip
                    content={
                      <p>
                        Shows how your query was processed by the query rewriter
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                {lastQueryMetadata ? (
                  <div className="space-y-3 text-sm">
                    <div>
                      <span className="font-medium text-gray-700">
                        Original Query:
                      </span>
                      <div className="mt-1 max-h-20 overflow-y-auto rounded-md border bg-white p-3 text-gray-800 shadow-sm">
                        {lastQueryMetadata.original_query}
                      </div>
                    </div>
                    <div>
                      <span className="font-medium text-gray-700">
                        Rewritten Query:
                      </span>
                      <div className="mt-1 max-h-20 overflow-y-auto rounded-md border bg-white p-3 text-gray-800 shadow-sm">
                        {lastQueryMetadata.final_query}
                      </div>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-blue-700">
                      <span className="font-medium">
                        Mode Used: {lastQueryMetadata.query_rewrite_mode}
                      </span>
                      <span className="font-medium">
                        Status:{' '}
                        {lastQueryMetadata.query_rewriting_enabled
                          ? 'Enabled'
                          : 'Disabled'}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="py-4 text-center text-sm text-gray-600">
                    <p className="mb-2">No query processed yet</p>
                    <p className="text-xs text-gray-500">
                      Submit a query to see how it gets rewritten for better
                      search results
                    </p>
                  </div>
                )}
              </div>

              {/* Query Rewrite Mode */}
              <div className="py-1">
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Query Rewrite Mode
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        <strong>Simple:</strong> Basic query optimization for
                        better search results
                        <br />
                        <strong>With Context:</strong> Enhanced optimization
                        with document context awareness
                        <br />
                        <strong>Filtered:</strong> Optimization with content
                        filtering for public/sensitive use
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <Select
                  value={settings.query_rewrite_mode}
                  onValueChange={handleQueryRewriteModeChange}
                  disabled={!settings.enable_query_rewriting}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent
                    align="start"
                    side="bottom"
                    className="w-[350px] max-w-[85vw]"
                  >
                    <SelectItem
                      value="simple"
                      className="focus:bg-blue-50 focus:text-blue-900"
                    >
                      Simple - Basic query optimization for search
                    </SelectItem>
                    <SelectItem
                      value="with_context"
                      className="focus:bg-blue-50 focus:text-blue-900"
                    >
                      With Context - Enhanced query optimization with document
                      retrieval
                    </SelectItem>
                    <SelectItem
                      value="filtered"
                      className="focus:bg-blue-50 focus:text-blue-900"
                    >
                      Filtered - Query optimization with content filtering for
                      public use
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Query Rewriter Prompt */}
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    <Label className="text-xs font-medium">
                      Query Rewriter Prompt
                    </Label>
                    <SimpleTooltip
                      content={
                        <p>
                          Customize the query rewriter behavior. Changes are
                          automatically saved.
                        </p>
                      }
                    >
                      <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                    </SimpleTooltip>
                  </div>
                  {settings.query_rewriter_prompt &&
                    settings.query_rewriter_prompt.trim() !==
                      DEFAULT_QUERY_REWRITER_PROMPTS[
                        settings.query_rewrite_mode
                      ].trim() && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          updateSetting(
                            'query_rewriter_prompt',
                            DEFAULT_QUERY_REWRITER_PROMPTS[
                              settings.query_rewrite_mode
                            ],
                          )
                        }
                        className="h-6 px-2 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                      >
                        <RotateCcw className="mr-1 h-3 w-3" />
                        Reset
                      </Button>
                    )}
                </div>
                <textarea
                  placeholder="Feel free to customize the query rewriter prompt..."
                  value={
                    settings.query_rewriter_prompt ||
                    DEFAULT_QUERY_REWRITER_PROMPTS[settings.query_rewrite_mode]
                  }
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                    updateSetting(
                      'query_rewriter_prompt',
                      e.target.value || undefined,
                    )
                  }
                  className="h-[200px] w-full resize-none rounded-lg border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 transition-all duration-200 placeholder:text-gray-400 hover:border-gray-300 focus:border-blue-500 focus:bg-blue-50/30 focus:shadow-sm focus:ring-0 focus:outline-none"
                  style={{
                    overflowY: 'auto',
                    overflowX: 'hidden',
                    scrollbarWidth: 'thin',
                    scrollbarColor: '#cbd5e1 #f1f5f9',
                  }}
                />
                <div className="mt-1 text-xs text-gray-500">
                  Query rewriter prompt - changes are automatically saved
                </div>
              </div>

              {/* Spacer for better scrolling */}
              <div className="h-4"></div>
            </TabsContent>

            <TabsContent
              value="database"
              className="hide-scrollbar flex-1 space-y-3 overflow-y-auto p-1"
            >
              {/* Collection Viewer */}
              <div className="py-1">
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium">
                    Collection Viewer
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        Browse and search through your Milvus vector database
                        collections
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <div className="hide-scrollbar h-20 overflow-y-auto rounded bg-gray-50 p-2">
                  <MilvusViewer />
                </div>
              </div>

              {/* Danger Zone */}
              <div className="border-t py-1 pt-1">
                <div className="mb-1 flex items-center gap-1">
                  <Label className="text-xs font-medium text-red-600">
                    Danger Zone
                  </Label>
                  <SimpleTooltip
                    content={
                      <p>
                        ⚠️ This will permanently delete all data and recreate
                        the database from scratch
                      </p>
                    }
                  >
                    <HelpCircle className="h-3 w-3 text-gray-400 hover:text-gray-600" />
                  </SimpleTooltip>
                </div>
                <Button className="h-7 w-full bg-red-600 text-xs text-white hover:bg-red-700">
                  Regenerate Database
                </Button>
              </div>
            </TabsContent>
          </Tabs>
        </div>
        <DialogFooter className="border-t pt-2">
          <div className="flex w-full items-center justify-between">
            <div
              className={`flex items-center gap-1 rounded-md px-2 py-1 transition-all duration-700 ease-out ${
                saveAnimation ? 'bg-green-50/80 shadow-sm' : 'bg-transparent'
              }`}
            >
              <div
                className={`h-1.5 w-1.5 rounded-full bg-green-500 transition-all duration-700 ease-out ${
                  saveAnimation
                    ? 'scale-150 shadow-lg shadow-green-500/50'
                    : 'scale-100'
                }`}
              ></div>
              <p
                className={`text-xs transition-all duration-700 ease-out ${
                  saveAnimation ? 'font-medium text-green-700' : 'text-gray-400'
                }`}
              >
                Auto-saved
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              className="h-7 px-3 text-xs hover:bg-gray-100 hover:text-gray-700"
            >
              Close
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
