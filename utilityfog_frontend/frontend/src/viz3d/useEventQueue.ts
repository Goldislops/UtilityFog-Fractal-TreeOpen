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
  // Lifetime guard: rAF callbacks scheduled while mounted can fire AFTER
  // unmount, and queued work must never invoke handlers then. Armed on
  // mount, disarmed (and the queue released) in cleanup; StrictMode's
  // mount→cleanup→mount cycle re-arms correctly.
  const activeRef = useRef(false)

  useEffect(() => {
    activeRef.current = true
    return () => {
      activeRef.current = false
      queueRef.current = []
    }
  }, [])

  const processQueue = useCallback(async () => {
    if (processingRef.current) return
    processingRef.current = true
    try {
      // The active guard is re-checked before EVERY handler (not merely
      // every batch): an unmount performed by a handler stops the rest of
      // its own batch, and an unmount between frames stops the drain.
      while (activeRef.current && queueRef.current.length > 0) {
        const batch = queueRef.current.splice(0, 10) // Process in batches of 10
        for (const fn of batch) {
          if (!activeRef.current) return
          try {
            fn()
          } catch (error) {
            // Handler-error policy: one failing handler must not lock the
            // queue, abort its batch-mates, or be retried. The failure is
            // reported exactly once through the bounded diagnostic channel
            // and later independent events process normally.
            console.error('Event handler failed:', error)
          }
        }

        // Schedule the next yield frame ONLY while still active with more
        // work queued — an unmount during the LAST handler (or an emptied
        // queue) must not request an extra animation frame.
        if (!activeRef.current || queueRef.current.length === 0) break
        // Allow browser to render
        await new Promise(resolve => requestAnimationFrame(resolve))
      }
    } finally {
      // Restoration lives in a finally boundary so no exit path — normal,
      // early-return on unmount, or a future throw — can leave the queue
      // permanently locked. Nothing in the loop rethrows, so this async
      // fire-and-forget drain also never yields an unhandled rejection.
      processingRef.current = false
    }
  }, [])

  const enqueueUpdate = useCallback(
    (updateFn: () => void) => {
      if (!activeRef.current) return
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