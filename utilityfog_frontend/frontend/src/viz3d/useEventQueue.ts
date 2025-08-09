import { useEffect, useRef } from 'react'
import { SimBridgeClient, NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'

interface EventQueueHandlers {
  updateNode: (node: NetworkNode) => void
  setNetwork: (nodes: NetworkNode[], edges: NetworkEdge[]) => void
}

export function useEventQueue(
  simClient: SimBridgeClient | null,
  handlers: EventQueueHandlers
) {
  const queueRef = useRef<Array<() => void>>([])
  const processingRef = useRef(false)

  const processQueue = async () => {
    if (processingRef.current) return
    processingRef.current = true

    while (queueRef.current.length > 0) {
      const batch = queueRef.current.splice(0, 10) // Process in batches of 10
      batch.forEach(fn => fn())
      
      // Allow browser to render
      await new Promise(resolve => requestAnimationFrame(resolve))
    }

    processingRef.current = false
  }

  const enqueueUpdate = (updateFn: () => void) => {
    queueRef.current.push(updateFn)
    if (!processingRef.current) {
      requestAnimationFrame(processQueue)
    }
  }

  useEffect(() => {
    if (!simClient) return

    const handleNetworkUpdate = (data: { nodes?: NetworkNode[], edges?: NetworkEdge[] }) => {
      if (data.nodes && data.edges) {
        enqueueUpdate(() => handlers.setNetwork(data.nodes!, data.edges!))
      }
    }

    const handleNodeUpdate = (node: NetworkNode) => {
      enqueueUpdate(() => handlers.updateNode(node))
    }

    const handleEdgeUpdate = (edge: NetworkEdge) => {
      // Handle edge updates if needed
      console.log('Edge update:', edge)
    }

    simClient.on('network_update', handleNetworkUpdate)
    simClient.on('node_update', handleNodeUpdate)
    simClient.on('edge_update', handleEdgeUpdate)

    return () => {
      simClient.off('network_update', handleNetworkUpdate)
      simClient.off('node_update', handleNodeUpdate)
      simClient.off('edge_update', handleEdgeUpdate)
    }
  }, [simClient, handlers])

  return {
    queueLength: queueRef.current.length,
    isProcessing: processingRef.current
  }
}