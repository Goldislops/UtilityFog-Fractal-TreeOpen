import { useCallback, useEffect, useRef } from 'react'
import { SimBridgeClient } from '../ws/SimBridgeClient'

interface EventQueueHandlers {
  updateNode: (node: unknown) => void
  setNetwork: (nodes: unknown, edges: unknown) => void
}

export function useEventQueue(
  simClient: SimBridgeClient | null,
  handlers: EventQueueHandlers
) {
  const queueRef = useRef<Array<() => void>>([])
  const processingRef = useRef(false)

  const processQueue = useCallback(async () => {
    if (processingRef.current) return
    processingRef.current = true

    while (queueRef.current.length > 0) {
      const batch = queueRef.current.splice(0, 10) // Process in batches of 10
      batch.forEach(fn => fn())
      
      // Allow browser to render
      await new Promise(resolve => requestAnimationFrame(resolve))
    }

    processingRef.current = false
  }, [])

  const enqueueUpdate = useCallback(
    (updateFn: () => void) => {
      queueRef.current.push(updateFn)
      if (!processingRef.current) {
        requestAnimationFrame(processQueue)
      }
    },
    [processQueue],
  )

  useEffect(() => {
    if (!simClient) return

    const handleNetworkUpdate = (data?: unknown) => {
      // Null/primitive payloads must not throw, and one malformed side
      // must not discard the other: forward whatever is present and let
      // the store's per-side validation decide (empty arrays stay
      // meaningful and clear their collection).
      if (!data || typeof data !== 'object') return
      const d = data as { nodes?: unknown; edges?: unknown }
      if (d.nodes !== undefined || d.edges !== undefined) {
        enqueueUpdate(() => handlers.setNetwork(d.nodes, d.edges))
      }
    }

    const handleNodeUpdate = (node?: unknown) => {
      enqueueUpdate(() => handlers.updateNode(node))
    }

    const handleEdgeUpdate = (edge?: unknown) => {
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
  }, [simClient, handlers, enqueueUpdate])

  return {
    queueLength: queueRef.current.length,
    isProcessing: processingRef.current
  }
}