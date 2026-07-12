import { create } from 'zustand'
import { NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'
import { applyNodeUpdate, sanitizeNodeList } from './nodeValidation'
import { sanitizeEdgeList } from './edgeValidation'

interface SceneStore {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  updateNode: (node: unknown) => void
  updateEdge: (edge: NetworkEdge) => void
  setNetwork: (nodes: unknown, edges: unknown) => void
  clearNetwork: () => void
}

export const useSceneStore = create<SceneStore>((set) => ({
  nodes: [],
  edges: [],

  updateNode: (node: unknown) =>
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

  setNetwork: (nodes: unknown, edges: unknown) =>
    set((state) => ({
      // Per-side tolerance: a malformed side never discards the valid
      // other side; explicit empty arrays remain meaningful and clear.
      // Both sides go through their shared materializing validators —
      // admitted records are plain owned objects (see nodeValidation.ts
      // and edgeValidation.ts for the contracts). Dangling REFERENCES on
      // well-formed edges stay tolerated (renderers skip unmatched ids).
      nodes: Array.isArray(nodes) ? sanitizeNodeList(nodes, state.nodes) : state.nodes,
      edges: sanitizeEdgeList(edges, state.edges),
    })),

  clearNetwork: () =>
    set({ nodes: [], edges: [] }),
}))