import { create } from 'zustand'
import { NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'
import { applyNodeUpdate, sanitizeNodeList } from './nodeValidation'

interface SceneStore {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  updateNode: (node: NetworkNode) => void
  updateEdge: (edge: NetworkEdge) => void
  setNetwork: (nodes: NetworkNode[], edges: NetworkEdge[]) => void
  clearNetwork: () => void
}

export const useSceneStore = create<SceneStore>((set) => ({
  nodes: [],
  edges: [],

  updateNode: (node: NetworkNode) =>
    set((state) => {
      // Ingestion boundary: malformed positions never reach the renderers
      // (see nodeValidation.ts for the reconcile contract).
      const nodes = applyNodeUpdate(state.nodes, node)
      return nodes === state.nodes ? {} : { nodes }
    }),

  updateEdge: (edge: NetworkEdge) =>
    set((state) => {
      const existingIndex = state.edges.findIndex(e => e.id === edge.id)
      
      if (existingIndex >= 0) {
        const newEdges = [...state.edges]
        newEdges[existingIndex] = edge
        return { edges: newEdges }
      } else {
        return { edges: [...state.edges, edge] }
      }
    }),

  setNetwork: (nodes: NetworkNode[], edges: NetworkEdge[]) =>
    set((state) => ({
      // Per-side tolerance: a malformed side never discards the valid
      // other side; explicit empty arrays remain meaningful and clear.
      nodes: Array.isArray(nodes) ? sanitizeNodeList(nodes, state.nodes) : state.nodes,
      edges: Array.isArray(edges) ? edges : state.edges,
    })),

  clearNetwork: () =>
    set({ nodes: [], edges: [] }),
}))