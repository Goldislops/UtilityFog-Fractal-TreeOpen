import { NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'

// Adapter functions to convert between different data formats.
// Raw simulation payloads are an external-data boundary: elements are
// narrowed to partial shapes and every field access keeps its runtime
// fallback, exactly as before.

interface RawAgent {
  id?: string
  position?: [number, number, number]
  connections?: string[]
  active?: boolean
}

interface RawConnection {
  id?: string
  source?: string
  target?: string
  from?: string
  to?: string
  strength?: number
  weight?: number
}

export function adaptSimulationData(rawData: unknown): {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
} {
  const nodes: NetworkNode[] = []
  const edges: NetworkEdge[] = []

  // Handle different possible data structures from the simulation
  const raw = (rawData ?? {}) as {
    agents?: unknown[]
    connections?: unknown[]
    nodes?: unknown[]
    edges?: unknown[]
  }
  if (raw.agents) {
    raw.agents.forEach((rawAgent: unknown, index: number) => {
      const agent = rawAgent as RawAgent
      nodes.push({
        id: agent.id || `agent_${index}`,
        position: agent.position || [
          Math.random() * 20 - 10,
          Math.random() * 20 - 10,
          Math.random() * 20 - 10
        ],
        connections: agent.connections || [],
        status: agent.active ? 'active' : 'inactive'
      })
    })
  }

  if (raw.connections) {
    raw.connections.forEach((rawConn: unknown, index: number) => {
      const conn = rawConn as RawConnection
      edges.push({
        id: conn.id || `edge_${index}`,
        // Legacy adapter tolerance preserved exactly: a connection with
        // neither field yields undefined at runtime (as before); edge
        // consumers skip dangling references.
        source: (conn.source || conn.from) as string,
        target: (conn.target || conn.to) as string,
        strength: conn.strength || conn.weight || 1
      })
    })
  }

  // Handle generic node/edge format
  if (raw.nodes) {
    raw.nodes.forEach((rawNode: unknown) => {
      const node = rawNode as Partial<NetworkNode> & { id: string }
      nodes.push({
        id: node.id,
        position: node.position || [0, 0, 0],
        connections: node.connections || [],
        status: node.status || 'active'
      })
    })
  }

  if (raw.edges) {
    raw.edges.forEach((rawEdge: unknown) => {
      const edge = rawEdge as Partial<NetworkEdge> & { id: string; source: string; target: string }
      edges.push({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        strength: edge.strength || 1
      })
    })
  }

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