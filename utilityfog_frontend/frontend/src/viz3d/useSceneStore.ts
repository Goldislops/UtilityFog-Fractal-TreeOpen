import { create } from 'zustand'
import { NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'

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
      const existingIndex = state.nodes.findIndex(n => n.id === node.id)
      
      if (existingIndex >= 0) {
        const newNodes = [...state.nodes]
        newNodes[existingIndex] = node
        return { nodes: newNodes }
      } else {
        return { nodes: [...state.nodes, node] }
      }
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
    set({ nodes, edges }),

  clearNetwork: () =>
    set({ nodes: [], edges: [] }),
}))