import { NetworkNode } from '../ws/SimBridgeClient'

// Ingestion-boundary validation for node visualization data. A malformed
// node payload from the transport must never crash a renderer: previously,
// a node_update without a valid position reached InstancedNodes
// (`tempObject.position.set(...node.position)`) and NetworkView2D
// (`node.position[0]`), throwing and unmounting the whole React tree.
// Transport (SimBridgeClient) is deliberately untouched: invalid
// visualization data must not affect WebSocket connectivity.

/// A position is valid only when it is an array of exactly three finite
/// numbers. (NaN/Infinity are rejected — they draw nothing meaningful and
/// poison instanced-matrix math.)
export function isValidPosition(p: unknown): p is [number, number, number] {
  return (
    Array.isArray(p) &&
    p.length === 3 &&
    p.every(v => typeof v === 'number' && Number.isFinite(v))
  )
}

/// Reconcile an incoming node-shaped payload against the previously known
/// node with the same id. Partial updates MERGE with the existing record
/// ({ ...existing, ...incoming }) so omitted fields such as `connections`
/// survive. Returns the node to store, or null when it must not reach any
/// renderer:
///  - valid incoming position → merged record with the incoming position;
///  - invalid/missing position on a node whose previous state holds a valid
///    position → merged record with the LAST VALID position preserved;
///  - previously unknown node without a valid position → null. No [0,0,0]
///    is ever invented; a later valid update recovers the node normally.
/// Required-field evidence (source-verified): the renderers read `id`
/// (matching), `position` (InstancedNodes matrix + 2D draw) and `status`
/// (color switches with safe defaults); `connections` is read by no
/// renderer. A previously unknown node with a valid position is therefore
/// admitted as supplied — no missing fields are invented.
export function reconcileNode(
  incoming: NetworkNode,
  existing: NetworkNode | undefined,
): NetworkNode | null {
  const merged = existing ? { ...existing, ...incoming } : incoming
  if (isValidPosition((incoming as { position?: unknown }).position)) {
    return merged
  }
  if (existing && isValidPosition(existing.position)) {
    return { ...merged, position: existing.position }
  }
  return null
}

/// Apply one incoming node to a node list (update-or-append by id),
/// enforcing the reconcile contract. Non-object payloads and payloads
/// without a string id are dropped (nothing to identify or render).
/// Mixed valid/invalid updates can never duplicate a node: matching is
/// always by id.
export function applyNodeUpdate(
  previous: NetworkNode[],
  incoming: NetworkNode,
): NetworkNode[] {
  const id = (incoming as { id?: unknown } | null | undefined)?.id
  if (typeof id !== 'string') return previous
  const index = previous.findIndex(n => n.id === id)
  const next = reconcileNode(incoming, index >= 0 ? previous[index] : undefined)
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
/// invalid positions past the boundary either.
export function sanitizeNodeList(
  incoming: NetworkNode[],
  previous: NetworkNode[],
): NetworkNode[] {
  if (!Array.isArray(incoming)) return previous
  const byId = new Map(previous.map(n => [n.id, n]))
  const result: NetworkNode[] = []
  const seen = new Set<string>()
  for (const candidate of incoming) {
    const id = (candidate as { id?: unknown } | null | undefined)?.id
    if (typeof id !== 'string' || seen.has(id)) continue
    const next = reconcileNode(candidate, byId.get(id))
    if (next !== null) {
      result.push(next)
      seen.add(id)
    }
  }
  return result
}
