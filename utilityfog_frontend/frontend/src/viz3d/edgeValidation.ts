import { NetworkEdge } from '../ws/SimBridgeClient'

// Shared edge ownership contract — the one ingestion validator for every
// surface that stores or renders edges (legacy adapter, scene store,
// NetworkView2D subscription).
//
// Renderer evidence (source-verified): consumers key on edge.id and index
// edge.source/edge.target against node ids; unmatched ids are skipped, so
// well-formed DANGLING references stay tolerated. Missing or non-string
// endpoints are rejected outright — endpoints are never invented and never
// silently stringified.
//
// Ownership: admitted edges are MATERIALIZED plain objects. Every field is
// read exactly once inside the containment boundary, so throwing getters
// reject the candidate and live getters can never reach stored state.

export interface EdgeMaterializeOptions {
  // Legacy adapter dialect: source/from and target/to aliases, and the
  // strength || weight || 1 fallback chain's weight leg.
  legacyAliases?: boolean
  // Legacy adapter id contract: a missing/falsy id takes the caller's
  // index-generated id (`edge_${index}`). The adapter is the only caller
  // that supplies this.
  fallbackId?: string
}

export function materializeEdge(
  incoming: unknown,
  opts: EdgeMaterializeOptions = {},
): NetworkEdge | null {
  if (!incoming || typeof incoming !== 'object') return null
  try {
    const source = incoming as Record<string, unknown>
    const rawId = 'id' in source ? source.id : undefined
    const rawSource = 'source' in source ? source.source : undefined
    const rawTarget = 'target' in source ? source.target : undefined
    const rawStrength = 'strength' in source ? source.strength : undefined
    const rawFrom = opts.legacyAliases && 'from' in source ? source.from : undefined
    const rawTo = opts.legacyAliases && 'to' in source ? source.to : undefined
    const rawWeight = opts.legacyAliases && 'weight' in source ? source.weight : undefined

    // The legacy || chains treated falsy values ('' ids, 0 strengths) as
    // absent — that contract is preserved exactly.
    const id = (typeof rawId === 'string' && rawId) || opts.fallbackId
    if (typeof id !== 'string' || id === '') return null

    const src =
      (typeof rawSource === 'string' && rawSource) ||
      (typeof rawFrom === 'string' && rawFrom) ||
      undefined
    const tgt =
      (typeof rawTarget === 'string' && rawTarget) ||
      (typeof rawTo === 'string' && rawTo) ||
      undefined
    if (src === undefined || tgt === undefined) return null

    const strength =
      (typeof rawStrength === 'number' && Number.isFinite(rawStrength) && rawStrength) ||
      (typeof rawWeight === 'number' && Number.isFinite(rawWeight) && rawWeight) ||
      1

    return { id, source: src, target: tgt, strength }
  } catch {
    // Hostile shapes (throwing getters, poisoned proxies) are contained at
    // the boundary exactly like any other malformed input.
    return null
  }
}

// Sanitize a wholesale edge list. Mirrors sanitizeNodeList: a non-array
// keeps the previous list (per-side tolerance); elements are materialized
// individually; duplicate ids keep the first occurrence.
//
// REFERENTIAL STABILITY: an admitted edge whose owned fields equal the
// previous edge with the same id REUSES that previous object, and when
// length, order and every element reference are unchanged the previous
// ARRAY reference is returned — no-op wholesale updates notify nobody.
export function sanitizeEdgeList(incoming: unknown, previous: NetworkEdge[]): NetworkEdge[] {
  if (!Array.isArray(incoming)) return previous
  const byId = new Map(previous.map(e => [e.id, e]))
  const result: NetworkEdge[] = []
  const seen = new Set<string>()
  for (const candidate of incoming) {
    const edge = materializeEdge(candidate)
    if (edge === null || seen.has(edge.id)) continue
    const prior = byId.get(edge.id)
    const unchanged =
      prior !== undefined &&
      prior.source === edge.source &&
      prior.target === edge.target &&
      prior.strength === edge.strength
    result.push(unchanged ? prior : edge)
    seen.add(edge.id)
  }
  if (result.length === previous.length && result.every((e, i) => e === previous[i])) {
    return previous
  }
  return result
}
