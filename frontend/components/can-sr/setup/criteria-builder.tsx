'use client'

import React, { useEffect, useMemo, useState } from 'react'
import yaml from 'js-yaml'

type AnswerMap = Record<string, string>

interface RawCriteriaConfig {
  include?: string[]
  criteria?: Record<string, AnswerMap>
  l2_criteria?: Record<string, AnswerMap>
  parameters?: Record<string, AnswerMap>
}

interface AnswerOption {
  id: string
  label: string
  description: string
}

interface QuestionGroup {
  id: string
  question: string
  answers: AnswerOption[]
}

interface CriteriaConfigUI {
  include: string[]
  criteria: QuestionGroup[]
  l2Criteria: QuestionGroup[]
  parameters: QuestionGroup[]
}

type TemplateKey = 'blank' | 'generic_infectious' | 'vaccine_safety'

interface CriteriaBuilderProps {
  yamlText: string
  onYamlChange: (nextYaml: string) => void
}

function makeId() {
  return Math.random().toString(36).slice(2, 10)
}

function mapToGroups(map?: Record<string, AnswerMap>): QuestionGroup[] {
  if (!map) return []
  return Object.entries(map).map(([question, answers]) => ({
    id: makeId(),
    question,
    answers: Object.entries(answers || {}).map(([label, description]) => ({
      id: makeId(),
      label,
      description: description ?? '',
    })),
  }))
}

function groupsToMap(groups: QuestionGroup[]): Record<string, AnswerMap> {
  const out: Record<string, AnswerMap> = {}
  for (const group of groups) {
    if (!group.question.trim()) continue
    const answerMap: AnswerMap = {}
    for (const ans of group.answers) {
      if (!ans.label.trim()) continue
      answerMap[ans.label] = ans.description ?? ''
    }
    if (Object.keys(answerMap).length > 0) {
      out[group.question] = answerMap
    }
  }
  return out
}

function parseYamlToUi(yamlText: string): CriteriaConfigUI {
  try {
    const parsed = (yaml.load(yamlText || '') || {}) as RawCriteriaConfig
    return {
      include: Array.isArray(parsed.include) ? parsed.include : [],
      criteria: mapToGroups(parsed.criteria),
      l2Criteria: mapToGroups(parsed.l2_criteria),
      parameters: mapToGroups(parsed.parameters),
    }
  } catch {
    // Fallback to empty config on parse errors
    return {
      include: [],
      criteria: [],
      l2Criteria: [],
      parameters: [],
    }
  }
}

function uiToYaml(ui: CriteriaConfigUI): string {
  const raw: RawCriteriaConfig = {
    include: ui.include,
    criteria: groupsToMap(ui.criteria),
    l2_criteria: groupsToMap(ui.l2Criteria),
    parameters: groupsToMap(ui.parameters),
  }

  return yaml.dump(raw, {
    lineWidth: 80,
    noRefs: true,
  })
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

const TEMPLATE_CONFIGS: Record<TemplateKey, CriteriaConfigUI> = {
  blank: {
    include: [],
    criteria: [],
    l2Criteria: [],
    parameters: [],
  },
  generic_infectious: {
    include: ['Title', 'Abstract', 'Keywords', 'Year', 'Journal'],
    criteria: [
      {
        id: makeId(),
        question: 'Is this article about an infectious disease of interest?',
        answers: [
          {
            id: makeId(),
            label: 'Yes - infectious disease of interest',
            description:
              'The article focuses primarily on an infectious disease or outbreak relevant to this review.',
          },
          {
            id: makeId(),
            label: 'No - not relevant (exclude)',
            description:
              'The article does not focus on an infectious disease of interest for this review.',
          },
        ],
      },
      {
        id: makeId(),
        question: 'Is this article primary research?',
        answers: [
          {
            id: makeId(),
            label: 'Yes - primary research',
            description:
              'A study where data are collected and/or analyzed by the authors (e.g., cohort, case-control, RCT, case series).',
          },
          {
            id: makeId(),
            label: 'No - review, editorial, or commentary',
            description:
              'Select this for narrative reviews, editorials, commentaries, guidelines, or opinion pieces.',
          },
        ],
      },
    ],
    l2Criteria: [
      {
        id: makeId(),
        question:
          'Does this study report human cases or human-to-human transmission?',
        answers: [
          {
            id: makeId(),
            label: 'Yes',
            description:
              'The full text reports human cases or evidence of human-to-human transmission.',
          },
          {
            id: makeId(),
            label: 'No (exclude)',
            description:
              'No human cases or human-to-human transmission are reported in the full text.',
          },
        ],
      },
    ],
    parameters: [
      {
        id: makeId(),
        question: 'What epidemiological parameters are reported in this study?',
        answers: [
          {
            id: makeId(),
            label: 'Attack rate',
            description:
              'Proportion of an at-risk population that contracts the disease during a specified time interval.',
          },
          {
            id: makeId(),
            label: 'Incidence rate',
            description:
              'Number of new cases per population in a specified time period.',
          },
        ],
      },
    ],
  },
  vaccine_safety: {
    include: [
      'Title',
      'Abstract',
      'Vaccine name',
      'Outcome',
      'Population',
      'Year',
    ],
    criteria: [
      {
        id: makeId(),
        question: 'Is this article about vaccine safety?',
        answers: [
          {
            id: makeId(),
            label: 'Yes - vaccine safety',
            description:
              'The primary focus is on safety outcomes, adverse events, or tolerability of a vaccine.',
          },
          {
            id: makeId(),
            label: 'No - not about safety (exclude)',
            description:
              'The article focuses on efficacy, immunogenicity, or other topics without meaningful safety data.',
          },
        ],
      },
      {
        id: makeId(),
        question:
          'Does the population match the review scope (e.g., age group, risk group)?',
        answers: [
          {
            id: makeId(),
            label: 'Yes - population in scope',
            description:
              'The population characteristics (e.g., age, risk group) align with the review eligibility criteria.',
          },
          {
            id: makeId(),
            label: 'No - population out of scope (exclude)',
            description:
              'The study population is clearly outside the target population for this review.',
          },
        ],
      },
    ],
    l2Criteria: [
      {
        id: makeId(),
        question:
          'Does the full text provide quantitative safety outcomes (e.g., rates, counts) for the vaccine(s)?',
        answers: [
          {
            id: makeId(),
            label: 'Yes',
            description:
              'The full text reports quantitative safety outcomes (e.g., adverse event counts, incidence, rates).',
          },
          {
            id: makeId(),
            label: 'No (exclude)',
            description:
              'Only qualitative statements about safety are provided; no extractable quantitative outcomes.',
          },
        ],
      },
    ],
    parameters: [
      {
        id: makeId(),
        question: 'Which safety outcomes are reported?',
        answers: [
          {
            id: makeId(),
            label: 'Serious adverse events',
            description:
              'Any serious adverse event definition as reported by study authors (e.g., hospitalization, life-threatening event).',
          },
          {
            id: makeId(),
            label: 'Local reactions',
            description:
              'Injection site reactions such as pain, redness, or swelling.',
          },
          {
            id: makeId(),
            label: 'Systemic reactions',
            description:
              'Systemic symptoms such as fever, fatigue, myalgia, or headache.',
          },
        ],
      },
    ],
  },
}

const TEMPLATE_LABELS: Record<TemplateKey, string> = {
  blank: 'Start from blank configuration',
  generic_infectious: 'Generic infectious disease review',
  vaccine_safety: 'Vaccine safety review',
}

export function CriteriaBuilder({
  yamlText,
  onYamlChange,
}: CriteriaBuilderProps) {
  const [template, setTemplate] = useState<TemplateKey>('blank')
  const [config, setConfig] = useState<CriteriaConfigUI>(() =>
    parseYamlToUi(yamlText),
  )

  // Re-sync from external yaml when it changes (e.g., reload last saved or upload)
  useEffect(() => {
    setConfig(parseYamlToUi(yamlText))
  }, [yamlText])

  // Whenever config changes, emit updated YAML
  useEffect(() => {
    const nextYaml = uiToYaml(config)
    onYamlChange(nextYaml)
  }, [config, onYamlChange])

  const handleTemplateChange = (key: TemplateKey) => {
    setTemplate(key)
    const tpl = TEMPLATE_CONFIGS[key]
    if (tpl) {
      // Use a fresh copy to avoid id collisions
      const fresh: CriteriaConfigUI = {
        include: [...tpl.include],
        criteria: tpl.criteria.map((g) => ({
          id: makeId(),
          question: g.question,
          answers: g.answers.map((a) => ({
            id: makeId(),
            label: a.label,
            description: a.description,
          })),
        })),
        l2Criteria: tpl.l2Criteria.map((g) => ({
          id: makeId(),
          question: g.question,
          answers: g.answers.map((a) => ({
            id: makeId(),
            label: a.label,
            description: a.description,
          })),
        })),
        parameters: tpl.parameters.map((g) => ({
          id: makeId(),
          question: g.question,
          answers: g.answers.map((a) => ({
            id: makeId(),
            label: a.label,
            description: a.description,
          })),
        })),
      }
      setConfig(fresh)
    }
  }

  const [includeInput, setIncludeInput] = useState('')

  const addInclude = () => {
    const trimmed = includeInput.trim()
    if (!trimmed) return
    setConfig((prev) => ({
      ...prev,
      include: [...prev.include, trimmed],
    }))
    setIncludeInput('')
  }

  const removeInclude = (idx: number) => {
    setConfig((prev) => ({
      ...prev,
      include: prev.include.filter((_, i) => i !== idx),
    }))
  }

  const addQuestion = (section: 'criteria' | 'l2Criteria' | 'parameters') => {
    setConfig((prev) => ({
      ...prev,
      [section]: [
        ...prev[section],
        {
          id: makeId(),
          question: '',
          answers: [
            {
              id: makeId(),
              label: '',
              description: '',
            },
          ],
        },
      ],
    }))
  }

  const updateQuestion = (
    section: 'criteria' | 'l2Criteria' | 'parameters',
    id: string,
    question: string,
  ) => {
    setConfig((prev) => ({
      ...prev,
      [section]: prev[section].map((g) =>
        g.id === id ? { ...g, question } : g,
      ),
    }))
  }

  const removeQuestion = (
    section: 'criteria' | 'l2Criteria' | 'parameters',
    id: string,
  ) => {
    setConfig((prev) => ({
      ...prev,
      [section]: prev[section].filter((g) => g.id !== id),
    }))
  }

  const addAnswer = (
    section: 'criteria' | 'l2Criteria' | 'parameters',
    questionId: string,
  ) => {
    setConfig((prev) => ({
      ...prev,
      [section]: prev[section].map((g) =>
        g.id === questionId
          ? {
              ...g,
              answers: [
                ...g.answers,
                {
                  id: makeId(),
                  label: '',
                  description: '',
                },
              ],
            }
          : g,
      ),
    }))
  }

  const updateAnswer = (
    section: 'criteria' | 'l2Criteria' | 'parameters',
    questionId: string,
    answerId: string,
    field: 'label' | 'description',
    value: string,
  ) => {
    setConfig((prev) => ({
      ...prev,
      [section]: prev[section].map((g) =>
        g.id === questionId
          ? {
              ...g,
              answers: g.answers.map((a) =>
                a.id === answerId ? { ...a, [field]: value } : a,
              ),
            }
          : g,
      ),
    }))
  }

  const removeAnswer = (
    section: 'criteria' | 'l2Criteria' | 'parameters',
    questionId: string,
    answerId: string,
  ) => {
    setConfig((prev) => ({
      ...prev,
      [section]: prev[section].map((g) =>
        g.id === questionId
          ? {
              ...g,
              answers: g.answers.filter((a) => a.id !== answerId),
            }
          : g,
      ),
    }))
  }

  const hasContent = useMemo(
    () =>
      config.include.length > 0 ||
      config.criteria.length > 0 ||
      config.l2Criteria.length > 0 ||
      config.parameters.length > 0,
    [config],
  )

  return (
    <div className="space-y-4">
      {/* Template selector */}
      <div className="flex flex-col gap-2 rounded-md border border-emerald-100 bg-emerald-50/60 p-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-emerald-900">
              Criteria templates
            </p>
            <p className="text-xs text-emerald-800/80">
              Start from a curated template or build your own configuration.
            </p>
          </div>
          <div className="min-w-[240px]">
            <select
              value={template}
              onChange={(e) =>
                handleTemplateChange(e.target.value as TemplateKey)
              }
              className="w-full rounded-md border border-emerald-300 bg-white px-2 py-1.5 text-sm text-emerald-900 shadow-sm focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 focus:outline-none"
            >
              {Object.entries(TEMPLATE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {hasContent && (
          <p className="text-xs text-emerald-800/80">
            You can freely edit questions and answers below after choosing a
            template.
          </p>
        )}
      </div>

      {/* Include fields */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-sm font-semibold text-gray-900">
              Fields to include from citation CSV
            </h4>
            <p className="text-xs text-gray-500">
              These columns will be combined into the text sent to the AI for
              screening.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {config.include.map((field, idx) => (
            <span
              key={`${field}-${idx}`}
              className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-800"
            >
              {field}
              <button
                type="button"
                onClick={() => removeInclude(idx)}
                className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full text-emerald-700 hover:bg-emerald-100"
                aria-label={`Remove ${field}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={includeInput}
            onChange={(e) => setIncludeInput(e.target.value)}
            placeholder="e.g., Title"
            className="flex-1 rounded-md border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={addInclude}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
          >
            Add field
          </button>
        </div>
      </section>

      {/* Helper to render a section (L1, L2, parameters) */}
      <SectionEditor
        title="Title & abstract screening questions (L1)"
        description="Questions used when screening titles and abstracts."
        sectionKey="criteria"
        groups={config.criteria}
        onAddQuestion={() => addQuestion('criteria')}
        onUpdateQuestion={(id, q) => updateQuestion('criteria', id, q)}
        onRemoveQuestion={(id) => removeQuestion('criteria', id)}
        onAddAnswer={(qid) => addAnswer('criteria', qid)}
        onUpdateAnswer={(qid, aid, field, value) =>
          updateAnswer('criteria', qid, aid, field, value)
        }
        onRemoveAnswer={(qid, aid) => removeAnswer('criteria', qid, aid)}
      />

      <SectionEditor
        title="Full-text screening questions (L2)"
        description="Additional questions applied when full text is available."
        sectionKey="l2Criteria"
        groups={config.l2Criteria}
        onAddQuestion={() => addQuestion('l2Criteria')}
        onUpdateQuestion={(id, q) => updateQuestion('l2Criteria', id, q)}
        onRemoveQuestion={(id) => removeQuestion('l2Criteria', id)}
        onAddAnswer={(qid) => addAnswer('l2Criteria', qid)}
        onUpdateAnswer={(qid, aid, field, value) =>
          updateAnswer('l2Criteria', qid, aid, field, value)
        }
        onRemoveAnswer={(qid, aid) => removeAnswer('l2Criteria', qid, aid)}
      />

      <SectionEditor
        title="Extraction parameters"
        description="Parameters you want the AI to extract from included studies."
        sectionKey="parameters"
        groups={config.parameters}
        onAddQuestion={() => addQuestion('parameters')}
        onUpdateQuestion={(id, q) => updateQuestion('parameters', id, q)}
        onRemoveQuestion={(id) => removeQuestion('parameters', id)}
        onAddAnswer={(qid) => addAnswer('parameters', qid)}
        onUpdateAnswer={(qid, aid, field, value) =>
          updateAnswer('parameters', qid, aid, field, value)
        }
        onRemoveAnswer={(qid, aid) => removeAnswer('parameters', qid, aid)}
      />

      <p className="text-xs text-gray-500">
        Changes you make here are saved as a structured configuration and sent
        to the backend as YAML. You no longer need to edit YAML directly.
      </p>
    </div>
  )
}

interface SectionEditorProps {
  title: string
  description: string
  sectionKey: string
  groups: QuestionGroup[]
  onAddQuestion: () => void
  onUpdateQuestion: (id: string, question: string) => void
  onRemoveQuestion: (id: string) => void
  onAddAnswer: (questionId: string) => void
  onUpdateAnswer: (
    questionId: string,
    answerId: string,
    field: 'label' | 'description',
    value: string,
  ) => void
  onRemoveAnswer: (questionId: string, answerId: string) => void
}

function SectionEditor({
  title,
  description,
  groups,
  onAddQuestion,
  onUpdateQuestion,
  onRemoveQuestion,
  onAddAnswer,
  onUpdateAnswer,
  onRemoveAnswer,
}: SectionEditorProps) {
  return (
    <section className="space-y-3 rounded-md border border-gray-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-gray-900">{title}</h4>
          <p className="text-xs text-gray-500">{description}</p>
        </div>
        <button
          type="button"
          onClick={onAddQuestion}
          className="rounded-md border border-emerald-500 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
        >
          Add question
        </button>
      </div>

      {groups.length === 0 && (
        <p className="text-xs text-gray-400">
          No questions yet. Click &quot;Add question&quot; to get started.
        </p>
      )}

      <div className="space-y-3">
        {groups.map((group, idx) => (
          <div
            key={group.id}
            className="rounded-md border border-gray-100 bg-gray-50/60 p-3"
          >
            <div className="mb-2 flex items-start justify-between gap-2">
              <div className="flex-1">
                <label className="block text-xs font-medium text-gray-700">
                  Question {idx + 1}
                </label>
                <input
                  type="text"
                  value={group.question}
                  onChange={(e) => onUpdateQuestion(group.id, e.target.value)}
                  placeholder="e.g., Is this article primary research?"
                  className="mt-1 w-full rounded-md border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 focus:outline-none"
                />
              </div>
              <button
                type="button"
                onClick={() => onRemoveQuestion(group.id)}
                className="mt-5 inline-flex h-7 items-center justify-center rounded-md border border-red-200 bg-red-50 px-2 text-xs font-medium text-red-700 hover:bg-red-100"
              >
                Remove
              </button>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-medium text-gray-700">
                Possible answers
              </p>
              {group.answers.map((ans) => (
                <div
                  key={ans.id}
                  className="rounded-md border border-gray-200 bg-white p-2"
                >
                  <div className="mb-1 flex items-start gap-2">
                    <div className="flex-1">
                      <label className="block text-[11px] font-medium text-gray-600">
                        Answer label
                      </label>
                      <input
                        type="text"
                        value={ans.label}
                        onChange={(e) =>
                          onUpdateAnswer(
                            group.id,
                            ans.id,
                            'label',
                            e.target.value,
                          )
                        }
                        placeholder='e.g., "Yes - primary research"'
                        className="mt-1 w-full rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 focus:outline-none"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => onRemoveAnswer(group.id, ans.id)}
                      className="mt-5 inline-flex h-6 items-center justify-center rounded-md border border-red-200 bg-red-50 px-2 text-[11px] font-medium text-red-700 hover:bg-red-100"
                    >
                      Remove
                    </button>
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-gray-600">
                      Description / guidance
                    </label>
                    <textarea
                      value={ans.description}
                      onChange={(e) =>
                        onUpdateAnswer(
                          group.id,
                          ans.id,
                          'description',
                          e.target.value,
                        )
                      }
                      rows={3}
                      className="mt-1 w-full resize-y rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 focus:outline-none"
                      placeholder="Provide guidance on when the reviewer should pick this answer."
                    />
                  </div>
                </div>
              ))}
              <button
                type="button"
                onClick={() => onAddAnswer(group.id)}
                className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                Add answer option
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
