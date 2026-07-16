// Package AL (amendment): chunk-load-error classifier.
//
// MEASURED PLATFORM LIMIT (request-log receipt on #345): after a
// network-failed dynamic import, Chromium's module map caches the
// rejection for that URL — a later import() of the SAME specifier
// re-rejects instantly with no new network request. A fresh React.lazy
// wrapper therefore cannot recover such a failure, and advertising a
// Retry action for it would be a false promise. The boundary uses this
// classifier to offer "Reload application" instead.
//
// The patterns are the ACTUAL dynamic-import failure message forms of
// the three engines in the test matrix — deliberately narrow so that
// ordinary render errors (including a bare fetch()'s "Failed to fetch")
// are never misclassified:
//  - Chromium: TypeError: Failed to fetch dynamically imported module: <url>
//  - Firefox:  TypeError: error loading dynamically imported module: <url>
//  - WebKit:   TypeError: Importing a module script failed.
export function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return (
    /Failed to fetch dynamically imported module/i.test(error.message) ||
    /error loading dynamically imported module/i.test(error.message) ||
    /Importing a module script failed/i.test(error.message)
  )
}
