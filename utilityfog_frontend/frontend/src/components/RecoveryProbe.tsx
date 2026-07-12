import { useEffect } from 'react'

// Package AK: commit probe for ViewErrorBoundary's success-aware focus
// contract. Rendered INSIDE the boundary-owned suspense boundary, after
// the real children — its effect can only run once the suspended
// children have revealed, i.e. the child commit the focus contract keys
// on. It fires on every subsequent commit too; the boundary gates on
// its retry flag. Lives in its own module so the boundary file exports
// only the boundary (react-refresh/only-export-components).
export default function RecoveryProbe({ onCommit }: { onCommit: () => void }) {
  useEffect(() => {
    onCommit()
  })
  return null
}
