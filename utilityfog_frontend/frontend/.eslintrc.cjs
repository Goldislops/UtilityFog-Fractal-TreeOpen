// Minimal ESLint 8 legacy configuration for the existing lint script
// (`eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0`).
// TypeScript-aware via the exact-pinned @typescript-eslint v8 pair.
// Unused-variable checks are deliberately OFF here: the compiler owns that
// gate (tsc --noEmit with noUnusedLocals), avoiding double-reporting.
module.exports = {
  root: true,
  env: { browser: true, es2021: true },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  settings: {
    react: { version: 'detect' },
  },
  plugins: ['@typescript-eslint', 'react', 'react-hooks', 'react-refresh'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
  ],
  rules: {
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
  overrides: [
    {
      // react-three-fiber renders custom reconciler elements whose props
      // (position/args/intensity/...) the React plugin cannot know; the
      // rule is scoped off for the 3D scene files only.
      files: ['src/viz3d/**/*.tsx'],
      rules: { 'react/no-unknown-property': 'off' },
    },
  ],
  ignorePatterns: [
    'dist/',
    'node_modules/',
    'playwright-report/',
    'test-results/',
    'coverage/',
  ],
}
