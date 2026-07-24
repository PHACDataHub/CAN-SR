import { describe, expect, it } from 'vitest'
import { flattenExtractionParameters } from './extraction-parameters'

describe('flattenExtractionParameters', () => {
  it('keeps canonical parameters flat and preserves selection options', () => {
    expect(
      flattenExtractionParameters({
        items: [
          {
            name: 'Design',
            description: 'Study design',
            type: 'selection',
            options: [{ label: 'RCT', context: 'Randomized' }],
          },
          { name: 'Sample size', description: 'N' },
        ],
      }),
    ).toEqual([
      {
        name: 'Design',
        description: 'Study design',
        unit_instructions: '',
        calculation: '',
        options: ['RCT'],
        option_contexts: { RCT: 'Randomized' },
      },
      {
        name: 'Sample size',
        description: 'N',
        unit_instructions: '',
        calculation: '',
        options: [],
        option_contexts: {},
      },
    ])
  })

  it('flattens legacy category arrays without exposing category headers', () => {
    expect(
      flattenExtractionParameters({
        categories: ['Outcomes', 'Population'],
        possible_parameters: [['Rate'], ['Age', 'Sex']],
        descriptions: [['rate desc'], ['age desc', '<desc>sex desc</desc>']],
      }).map(({ name, description }) => ({ name, description })),
    ).toEqual([
      { name: 'Rate', description: 'rate desc' },
      { name: 'Age', description: 'age desc' },
      { name: 'Sex', description: 'sex desc' },
    ])
  })
})
