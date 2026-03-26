import { dirname } from 'path'
import { fileURLToPath } from 'url'
import { FlatCompat } from '@eslint/eslintrc'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const compat = new FlatCompat({
  baseDirectory: __dirname,
})

const eslintConfig = [
  // Ignore build artifacts and dependencies
  {
    ignores: ['.next/**', 'node_modules/**'],
  },

  ...compat.extends('next/core-web-vitals', 'next/typescript'),

  // Global ignores (Flat Config)
  {
    ignores: ['.next/**', 'node_modules/**', 'out/**', 'dist/**', 'build/**'],
  },

  // Add custom rules override
  {
    files: ['**/*.ts', '**/*.tsx'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
]

export default eslintConfig
