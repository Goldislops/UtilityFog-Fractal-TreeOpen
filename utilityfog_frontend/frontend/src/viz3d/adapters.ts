import { NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'

// Adapter functions to convert between different data formats

export function adaptSimulationData(rawData: any): {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
} {
  const nodes: NetworkNode[] = []
  const edges: NetworkEdge[] = []

  // Handle different possible data structures from the simulation
  if (rawData.agents) {
    rawData.agents.forEach((agent: any, index: number) => {
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

  if (rawData.connections) {
    rawData.connections.forEach((conn: any, index: number) => {
      edges.push({
        id: conn.id || `edge_${index}`,
        source: conn.source || conn.from,
        target: conn.target || conn.to,
        strength: conn.strength || conn.weight || 1
      })
    })
  }

  // Handle generic node/edge format
  if (rawData.nodes) {
    rawData.nodes.forEach((node: any) => {
      nodes.push({
        id: node.id,
        position: node.position || [0, 0, 0],
        connections: node.connections || [],
        status: node.status || 'active'
      })
    })
  }

  if (rawData.edges) {
    rawData.edges.forEach((edge: any) => {
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