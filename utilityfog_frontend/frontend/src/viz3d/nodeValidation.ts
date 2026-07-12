import { NetworkNode } from '../ws/SimBridgeClient'

// Ingestion-boundary validation for node visualization data. A malformed
// node payload from the transport must never crash a renderer: previously,
// a node_update without a valid position reached InstancedNodes
// (`tempObject.position.set(...node.position)`) and NetworkView2D
// (`node.position[0]`), throwing and unmounting the whole React tree.
// Transport (SimBridgeClient) is deliberately untouched: invalid
// visualization data must not affect WebSocket connectivity.
//
// OWNERSHIP CONTRACT: admitted nodes are MATERIALIZED — every
// renderer-consumed field is read exactly once inside a containment
// boundary into a plain owned object. The untrusted incoming object (with
// any live getters, proxies or extra fields) never reaches stored state,
// and a throwing getter on ANY read field rejects the candidate.
//
// FIELD CONTRACT (audit-hardened):
//  - id: nonempty string, enforced at EVERY public admission seam.
//  - position: exactly three finite numbers, copied into an owned tuple.
//  - status: validated against the real NetworkNode union; an invalid
//    value is DISCARDED AS ABSENT (the renderers' documented default-color
//    path covers status-less records) — an update never fails solely on a
//    bad status, and it can never clobber a valid existing status.
//  - connections: owned copy retaining STRING elements only; a non-array
//    value is treated as absent. No untrusted array reference is retained.
//
// REFERENTIAL STABILITY: when an update changes nothing, the EXISTING
// object (and, list-wise, the previous ARRAY) is returned unchanged so
// subscribers are not notified for no-op updates; changed records always
// get fresh owned references.

const VALID_STATUSES: ReadonlyArray<NetworkNode['status']> = ['active', 'inactive', 'error']

/// Type PREDICATE (not an assertion): narrows only when the value really
/// is one of the union members.
export function isValidStatus(v: unknown): v is NetworkNode['status'] {
  return typeof v === 'string' && (VALID_STATUSES as readonly string[]).includes(v)
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v !== ''
}

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

/// Owned string-only copy of a connections candidate; null when the value
/// is not an array (treated as absent by the merge). Elements are read
/// once; non-string elements are dropped.
function readStringArray(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null
  const out: string[] = []
  for (const item of v) {
    if (typeof item === 'string') out.push(item)
  }
  return out
}

/// One single-pass, contained read of an untrusted node payload: every
/// renderer-relevant field is pulled into plain owned locals exactly once.
/// Returns null for non-objects and for ANY throw during reading
/// (hostile getters, poisoned `in`/ownKeys proxy traps).
interface NodeCandidate {
  hasId: boolean
  id: unknown
  position: [number, number, number] | null
  hasConnections: boolean
  connections: string[] | null
  hasStatus: boolean
  status: NetworkNode['status'] | null
}

function readNodeCandidate(incoming: unknown): NodeCandidate | null {
  if (!incoming || typeof incoming !== 'object') return null
  try {
    const source = incoming as Record<string, unknown>
    const hasId = 'id' in source
    const id = hasId ? source.id : undefined
    const position = readPositionTriple('position' in source ? source.position : undefined)
    const hasConnections = 'connections' in source
    const connections = hasConnections ? readStringArray(source.connections) : null
    const hasStatus = 'status' in source
    const rawStatus = hasStatus ? source.status : undefined
    const status = isValidStatus(rawStatus) ? rawStatus : null
    return { hasId, id, position, hasConnections, connections, hasStatus, status }
  } catch {
    return null
  }
}

function sameStringArray(a: string[] | undefined, b: string[] | undefined): boolean {
  if (a === b) return true
  if (!a || !b || a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false
  }
  return true
}

/// Build the owned node from a contained read. Presence semantics mirror
/// the original `{ ...existing, ...incoming }` merge for VALID values: a
/// valid field present on the incoming payload wins; an absent (or
/// invalid — see the field contract above) field survives from the
/// existing record. Unknown extra fields are DROPPED. Position rules:
///  - valid incoming position → owned copy of it;
///  - otherwise, existing valid position → preserved;
///  - otherwise (unknown node without a valid position) → null. No
///    [0,0,0] is ever invented; a later valid update recovers normally.
/// When nothing changed, the EXISTING object is returned unchanged.
function reconcileCandidate(
  c: NodeCandidate,
  existing: NetworkNode | undefined,
): NetworkNode | null {
  const id = c.hasId ? c.id : existing?.id
  if (!isNonEmptyString(id)) return null

  let position: [number, number, number]
  if (c.position) {
    position = c.position
  } else if (existing && isValidPosition(existing.position)) {
    position = [existing.position[0], existing.position[1], existing.position[2]]
  } else {
    return null
  }

  // Invalid status/connections values behave as absent (contract above).
  const connections = c.connections !== null ? c.connections : existing?.connections
  const status = c.status !== null ? c.status : existing?.status

  if (
    existing &&
    id === existing.id &&
    position[0] === existing.position[0] &&
    position[1] === existing.position[1] &&
    position[2] === existing.position[2] &&
    status === existing.status &&
    sameStringArray(connections, existing.connections)
  ) {
    return existing
  }

  const owned = { id, position } as NetworkNode
  if (connections !== undefined) owned.connections = connections
  if (status !== undefined) owned.status = status
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
/// without a nonempty string id are dropped (nothing to identify or
/// render). Mixed valid/invalid updates can never duplicate a node:
/// matching is always by id. The payload is read ONCE (single contained
/// pass) — a hostile getter is never invoked twice. A no-op update
/// returns the previous ARRAY reference unchanged.
export function applyNodeUpdate(
  previous: NetworkNode[],
  incoming: unknown,
): NetworkNode[] {
  const candidate = readNodeCandidate(incoming)
  if (candidate === null || !isNonEmptyString(candidate.id)) return previous
  const index = previous.findIndex(n => n.id === candidate.id)
  const next = reconcileCandidate(candidate, index >= 0 ? previous[index] : undefined)
  if (next === null) return previous
  if (index >= 0) {
    if (next === previous[index]) return previous
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
/// occurrence. When length, order and every element reference are
/// unchanged, the previous ARRAY reference is returned.
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
    if (candidate === null || !isNonEmptyString(candidate.id) || seen.has(candidate.id)) continue
    const next = reconcileCandidate(candidate, byId.get(candidate.id))
    if (next !== null) {
      result.push(next)
      seen.add(candidate.id)
    }
  }
  if (result.length === previous.length && result.every((n, i) => n === previous[i])) {
    return previous
  }
  return result
}
