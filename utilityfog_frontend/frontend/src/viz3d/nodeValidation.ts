import { NetworkNode } from '../ws/SimBridgeClient'

// Ingestion-boundary validation for node visualization data. A malformed
// node payload from the transport must never crash a renderer: previously,
// a node_update without a valid position reached InstancedNodes
// (`tempObject.position.set(...node.position)`) and NetworkView2D
// (`node.position[0]`), throwing and unmounting the whole React tree.
// Transport (SimBridgeClient) is deliberately untouched: invalid
// visualization data must not affect WebSocket connectivity.
//
// OWNERSHIP CONTRACT (Package Y): admitted nodes are MATERIALIZED — every
// renderer-consumed field is read exactly once inside a containment
// boundary into a plain owned object. The untrusted incoming object (with
// any live getters, proxies or extra fields) never reaches stored state,
// and a throwing getter on ANY read field rejects the candidate.

/// A position is valid only when it is an array of exactly three finite
/// numbers. (NaN/Infinity are rejected — they draw nothing meaningful and
/// poison instanced-matrix math.)
export function isValidPosition(p: unknown): p is [number, number, number] {
  if (!Array.isArray(p) || p.length !== 3) return false
  // Indexed access, not every(): every() SKIPS holes in sparse arrays, so
  // Array(3) — length 3, zero coordinates — would validate vacuously.
  for (let i = 0; i < 3; i++) {
    const v: unknown = p[i]
    if (typeof v !== 'number' || !Number.isFinite(v)) return false
  }
  return true
}

/// Read a position candidate into an OWNED tuple, or null. Each index is
/// read exactly once (hostile index getters are invoked at most once, and
/// holes in sparse arrays read as undefined and fail the number check).
function readPositionTriple(p: unknown): [number, number, number] | null {
  if (!Array.isArray(p) || p.length !== 3) return null
  const x: unknown = p[0]
  const y: unknown = p[1]
  const z: unknown = p[2]
  if (typeof x !== 'number' || !Number.isFinite(x)) return null
  if (typeof y !== 'number' || !Number.isFinite(y)) return null
  if (typeof z !== 'number' || !Number.isFinite(z)) return null
  return [x, y, z]
}

/// One single-pass, contained read of an untrusted node payload: every
/// renderer-relevant field is pulled into plain locals exactly once.
/// Returns null for non-objects and for ANY throw during reading
/// (hostile getters, poisoned `in`/ownKeys proxy traps).
interface NodeCandidate {
  hasId: boolean
  id: unknown
  position: [number, number, number] | null
  hasConnections: boolean
  connections: unknown
  hasStatus: boolean
  status: unknown
}

function readNodeCandidate(incoming: unknown): NodeCandidate | null {
  if (!incoming || typeof incoming !== 'object') return null
  try {
    const source = incoming as Record<string, unknown>
    const hasId = 'id' in source
    const id = hasId ? source.id : undefined
    const position = readPositionTriple('position' in source ? source.position : undefined)
    const hasConnections = 'connections' in source
    const connections = hasConnections ? source.connections : undefined
    const hasStatus = 'status' in source
    const status = hasStatus ? source.status : undefined
    return { hasId, id, position, hasConnections, connections, hasStatus, status }
  } catch {
    return null
  }
}

/// Build the owned node from a contained read. Presence semantics mirror
/// the original `{ ...existing, ...incoming }` merge: a field present on
/// the incoming payload wins; an absent field survives from the existing
/// record. Unknown extra fields are DROPPED (ownership: only
/// renderer-consumed fields are stored). Position rules unchanged:
///  - valid incoming position → owned copy of it;
///  - otherwise, existing valid position → preserved;
///  - otherwise (unknown node without a valid position) → null. No
///    [0,0,0] is ever invented; a later valid update recovers normally.
/// Required-field evidence (source-verified): renderers read `id`
/// (matching), `position` (InstancedNodes matrix + 2D draw) and `status`
/// (color switches with safe defaults); `connections` is read by no
/// renderer — its VALUE stays tolerated as supplied.
function reconcileCandidate(
  c: NodeCandidate,
  existing: NetworkNode | undefined,
): NetworkNode | null {
  let position: [number, number, number]
  if (c.position) {
    position = c.position
  } else if (existing && isValidPosition(existing.position)) {
    position = [existing.position[0], existing.position[1], existing.position[2]]
  } else {
    return null
  }
  const owned = {
    id: (c.hasId ? c.id : existing?.id) as NetworkNode['id'],
    position,
  } as NetworkNode
  if (c.hasConnections) owned.connections = c.connections as NetworkNode['connections']
  else if (existing) owned.connections = existing.connections
  if (c.hasStatus) owned.status = c.status as NetworkNode['status']
  else if (existing) owned.status = existing.status
  return owned
}

/// Reconcile an incoming node-shaped payload against the previously known
/// node with the same id. See reconcileCandidate for the merge/position
/// contract; this public seam performs the contained single-pass read.
export function reconcileNode(
  incoming: unknown,
  existing: NetworkNode | undefined,
): NetworkNode | null {
  const candidate = readNodeCandidate(incoming)
  if (candidate === null) return null
  return reconcileCandidate(candidate, existing)
}

/// Apply one incoming node to a node list (update-or-append by id),
/// enforcing the reconcile contract. Non-object payloads and payloads
/// without a string id are dropped (nothing to identify or render).
/// Mixed valid/invalid updates can never duplicate a node: matching is
/// always by id. The payload is read ONCE (single contained pass) — a
/// hostile getter is never invoked twice.
export function applyNodeUpdate(
  previous: NetworkNode[],
  incoming: unknown,
): NetworkNode[] {
  const candidate = readNodeCandidate(incoming)
  if (candidate === null || typeof candidate.id !== 'string') return previous
  const index = previous.findIndex(n => n.id === candidate.id)
  const next = reconcileCandidate(candidate, index >= 0 ? previous[index] : undefined)
  if (next === null) return previous
  if (index >= 0) {
    const copy = [...previous]
    copy[index] = next
    return copy
  }
  return [...previous, next]
}

/// Sanitize a wholesale node list (network_update), reconciling each entry
/// against the previously known nodes so a bulk update cannot smuggle
/// invalid positions past the boundary either. Hostile entries are skipped
/// without losing the rest of the batch; duplicate ids keep the first
/// occurrence.
export function sanitizeNodeList(
  incoming: unknown,
  previous: NetworkNode[],
): NetworkNode[] {
  if (!Array.isArray(incoming)) return previous
  const byId = new Map(previous.map(n => [n.id, n]))
  const result: NetworkNode[] = []
  const seen = new Set<string>()
  for (const entry of incoming) {
    const candidate = readNodeCandidate(entry)
    if (candidate === null || typeof candidate.id !== 'string' || seen.has(candidate.id)) continue
    const next = reconcileCandidate(candidate, byId.get(candidate.id))
    if (next !== null) {
      result.push(next)
      seen.add(candidate.id)
    }
  }
  return result
}
