// Native ESLint 9 flat configuration (Package AI) — replaces the legacy
// .eslintrc.cjs with IDENTICAL policy. No compatibility shims: every
// plugin used here supports flat config natively at the pinned versions.
//
// Policy preserved exactly from the eslintrc era:
//   - TypeScript recommended rules (@typescript-eslint 8.63.0, unchanged)
//   - React + hooks + refresh behavior
//   - unused-variable checks OFF (tsc --noEmit with noUnusedLocals owns
//     that gate — no double reporting)
//   - @typescript-eslint/no-explicit-any: error
//   - react/no-unknown-property scoped OFF for src/viz3d/**/*.tsx only
//     (react-three-fiber reconciler props)
//   - generated/report/coverage ignores
//   - zero warnings allowed (--max-warnings 0 in the lint script)
//
// SCOPE preserved exactly: the old command linted --ext ts,tsx only, so
// *.js/*.mjs/*.cjs (scripts/, this file) stay unlinted here — widening
// lint scope would be a policy change and belongs to its own decision.
import js from '@eslint/js'
import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'

export default [
  {
    ignores: [
      'dist/',
      'node_modules/',
      'playwright-report/',
      'test-results/',
      'coverage/',
      // Scope parity with the eslintrc-era --ext ts,tsx (see header note).
      '**/*.js',
      '**/*.mjs',
      '**/*.cjs',
      // Deliberate rule-violation fixtures, linted ONLY by the
      // check-lint-rules script (with ignores disabled).
      'lint-fixtures/',
    ],
  },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    settings: {
      react: { version: 'detect' },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      react,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      // The eslintrc-era plugin:@typescript-eslint/recommended implicitly
      // layered eslint-recommended's TS OVERRIDES (no-undef and friends
      // OFF for TS files — the compiler owns undefined identifiers). The
      // flat spread of recommended.rules alone loses that layer; restore
      // it explicitly for exact policy parity.
      ...tsPlugin.configs['eslint-recommended'].overrides[0].rules,
      ...tsPlugin.configs.recommended.rules,
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // The automatic JSX runtime makes React imports unnecessary.
      'react/react-in-jsx-scope': 'off',
      // Components are typed via TypeScript props interfaces.
      'react/prop-types': 'off',
      // tsc (noUnusedLocals) owns unused checks — see header note.
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      'react-refresh/only-export-components': 'warn',
      '@typescript-eslint/no-explicit-any': 'error',
    },
  },
  {
    // react-three-fiber renders custom reconciler elements whose props
    // (position/args/intensity/...) the React plugin cannot know; the
    // rule is scoped off for the 3D scene files only.
    files: ['src/viz3d/**/*.tsx'],
    rules: { 'react/no-unknown-property': 'off' },
  },
]
