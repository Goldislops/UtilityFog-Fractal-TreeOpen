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

export const useSceneStore = create<SceneStore>((set, get) => ({
  nodes: [],
  edges: [],

  // No-op discipline: the validators return the PREVIOUS references for
  // updates that change nothing, and these actions then skip set()
  // entirely — zustand notifies subscribers on every set() (even an empty
  // partial produces a fresh merged state object), so skipping is the only
  // way an identical update reaches zero notifications.
  updateNode: (node: unknown) => {
    // Ingestion boundary: malformed positions never reach the renderers
    // (see nodeValidation.ts for the reconcile contract).
    const state = get()
    const nodes = applyNodeUpdate(state.nodes, node)
    if (nodes !== state.nodes) set({ nodes })
  },

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

  setNetwork: (nodes: unknown, edges: unknown) => {
    // Per-side tolerance: a malformed side never discards the valid
    // other side; explicit empty arrays remain meaningful and clear.
    // Both sides go through their shared materializing validators —
    // admitted records are plain owned objects (see nodeValidation.ts
    // and edgeValidation.ts for the contracts). Dangling REFERENCES on
    // well-formed edges stay tolerated (renderers skip unmatched ids).
    const state = get()
    const nextNodes = Array.isArray(nodes) ? sanitizeNodeList(nodes, state.nodes) : state.nodes
    const nextEdges = sanitizeEdgeList(edges, state.edges)
    if (nextNodes !== state.nodes || nextEdges !== state.edges) {
      set({ nodes: nextNodes, edges: nextEdges })
    }
  },

  clearNetwork: () =>
    set({ nodes: [], edges: [] }),
}))