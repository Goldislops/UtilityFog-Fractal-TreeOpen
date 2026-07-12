import { NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'
import { materializeEdge } from './edgeValidation'
import { isValidStatus } from './nodeValidation'

// Adapter functions to convert between different data formats.
// Raw simulation payloads are an external-data boundary. Ownership
// contract (Package Y/Z): every admitted record is MATERIALIZED — each
// field read exactly once inside a containment boundary — so hostile
// elements or poisoned container getters are skipped, never allowed to
// throw out of the adapter or to leave live getters in adapted output.
// The adapter's own legacy fallback contracts are preserved: falsy ids
// generate agent_/edge_ index ids; agents without a USABLE position take
// the documented random scatter; generic nodes without a usable position
// take the documented [0,0,0] — both adapter-dialect contracts, distinct
// from the validation boundary (nodeValidation.ts), which never invents.

/// Contained read of one dialect container: a poisoned getter or a
/// non-array value contributes nothing for THAT dialect without aborting
/// the other dialects.
function readArray(container: object, key: string): unknown[] | null {
  try {
    const value = (container as Record<string, unknown>)[key]
    return Array.isArray(value) ? value : null
  } catch {
    return null
  }
}

/// Owned position triple, or null. Each index is read exactly once.
function readTriple(p: unknown): [number, number, number] | null {
  if (!Array.isArray(p) || p.length !== 3) return null
  const x: unknown = p[0]
  const y: unknown = p[1]
  const z: unknown = p[2]
  if (typeof x !== 'number' || !Number.isFinite(x)) return null
  if (typeof y !== 'number' || !Number.isFinite(y)) return null
  if (typeof z !== 'number' || !Number.isFinite(z)) return null
  return [x, y, z]
}

/// Owned connection copy retaining STRING elements only — no untrusted
/// array reference or non-string element survives into adapted output.
function readStringElements(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  const out: string[] = []
  for (const item of v) {
    if (typeof item === 'string') out.push(item)
  }
  return out
}

/// Legacy agents dialect: id || agent_<index>, random-scatter position
/// fallback, active flag → status.
function readAgent(raw: unknown, index: number): NetworkNode | null {
  // Arrays are not records: without this check an array would satisfy the
  // object test, read as field-less, and mint a phantom node with a
  // generated id and fallback position.
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  try {
    const a = raw as Record<string, unknown>
    const id = 'id' in a ? a.id : undefined
    const position = readTriple('position' in a ? a.position : undefined)
    const connections = 'connections' in a ? a.connections : undefined
    const active = 'active' in a ? a.active : undefined
    return {
      id: (typeof id === 'string' && id) || `agent_${index}`,
      position: position ?? [
        Math.random() * 20 - 10,
        Math.random() * 20 - 10,
        Math.random() * 20 - 10,
      ],
      connections: readStringElements(connections),
      status: active ? 'active' : 'inactive',
    }
  } catch {
    return null
  }
}

/// Generic nodes dialect: string id required (nothing to key on without
/// one), [0,0,0] position fallback, status || 'active'.
function readGenericNode(raw: unknown): NetworkNode | null {
  // Arrays are not records (see readAgent).
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  try {
    const n = raw as Record<string, unknown>
    const id = 'id' in n ? n.id : undefined
    if (typeof id !== 'string' || id === '') return null
    const position = readTriple('position' in n ? n.position : undefined)
    const connections = 'connections' in n ? n.connections : undefined
    const status = 'status' in n ? n.status : undefined
    return {
      id,
      position: position ?? [0, 0, 0],
      connections: readStringElements(connections),
      // Validated against the real union; the source-evidenced fallback
      // ('active', the pre-existing || fallback for falsy values) also
      // covers invalid non-falsy values — never a type assertion.
      status: isValidStatus(status) ? status : 'active',
    }
  } catch {
    return null
  }
}

export function adaptSimulationData(rawData: unknown): {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
} {
  const nodes: NetworkNode[] = []
  const edges: NetworkEdge[] = []
  if (!rawData || typeof rawData !== 'object') return { nodes, edges }

  const agents = readArray(rawData, 'agents')
  const connections = readArray(rawData, 'connections')
  const genericNodes = readArray(rawData, 'nodes')
  const genericEdges = readArray(rawData, 'edges')

  agents?.forEach((rawAgent, index) => {
    const node = readAgent(rawAgent, index)
    if (node) nodes.push(node)
  })

  connections?.forEach((rawConn, index) => {
    // Shared edge ownership contract (edgeValidation.ts) in its legacy
    // dialect: source/from + target/to aliases, strength||weight||1
    // fallback, and the index-generated id for missing/falsy ids.
    // Connections without string endpoints are rejected (endpoints are
    // never invented); well-formed dangling references stay admitted.
    const edge = materializeEdge(rawConn, { legacyAliases: true, fallbackId: `edge_${index}` })
    if (edge) edges.push(edge)
  })

  genericNodes?.forEach(rawNode => {
    const node = readGenericNode(rawNode)
    if (node) nodes.push(node)
  })

  genericEdges?.forEach(rawEdge => {
    // Generic dialect of the same contract: string id/source/target
    // required (no aliases, no generated ids), strength||1 preserved.
    const edge = materializeEdge(rawEdge)
    if (edge) edges.push(edge)
  })

  // Duplicate ids pass through untouched: the adapter transforms formats;
  // deduplication belongs to the store boundary (sanitizeNodeList /
  // sanitizeEdgeList).
  return { nodes, edges }
}

export function generateRandomNetwork(nodeCount: number = 50): {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
} {
  const nodes: NetworkNode[] = []
  const edges: NetworkEdge[] = []

  // Generate nodes
  for (let i = 0; i < nodeCount; i++) {
    nodes.push({
      id: `node_${i}`,
      position: [
        Math.random() * 40 - 20,
        Math.random() * 40 - 20,
        Math.random() * 40 - 20
      ],
      connections: [],
      status: Math.random() > 0.1 ? 'active' : 'inactive'
    })
  }

  // Generate edges
  const edgeCount = Math.floor(nodeCount * 1.5)
  for (let i = 0; i < edgeCount; i++) {
    const source = Math.floor(Math.random() * nodeCount)
    const target = Math.floor(Math.random() * nodeCount)
    
    if (source !== target) {
      edges.push({
        id: `edge_${i}`,
        source: `node_${source}`,
        target: `node_${target}`,
        strength: Math.random()
      })

      nodes[source].connections.push(`node_${target}`)
    }
  }

  return { nodes, edges }
}