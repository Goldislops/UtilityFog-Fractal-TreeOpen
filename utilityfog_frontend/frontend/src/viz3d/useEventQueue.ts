import { useCallback, useEffect, useMemo, useRef } from 'react'
import { SimBridgeClient } from '../ws/SimBridgeClient'
import {
  NodeUpdateCandidate,
  foldNodeUpdates,
  nodeUpdatePayload,
  readNodeUpdate,
} from './nodeValidation'

interface EventQueueHandlers {
  updateNode: (node: unknown) => void
  setNetwork: (nodes: unknown, edges: unknown) => void
}

export interface EventQueueOptions {
  // Deterministic test seam. The default is derived from measured evidence
  // (see DEFAULT_MAX_PENDING_NODES); read once at mount.
  maxPendingNodes?: number
}

export interface EventQueueStats {
  // Stable counters (a live object, mutated in place — a diagnostic/test
  // seam, deliberately not reactive state).
  coalesced: number
  superseded: number
  dropped: number
  invalidDropped: number
}

// TYPED QUEUE (Package AF). The previous queue stored arbitrary closures:
// unbounded growth under bursts, one rAF callback scheduled PER enqueue
// before the first drain ran (measured: 15 synchronous enqueues scheduled
// 15 frames), and invalid payloads occupied queue slots. This queue stores
// typed work instead:
//   - pendingSnapshot: the latest authoritative network_update, kept per
//     side (a newer nodes/edges side replaces the older queued one);
//   - pendingUpdates: post-snapshot node updates keyed by id in insertion
//     order, folded latest-valid-wins per field (see nodeValidation's
//     foldNodeUpdates for the sequential-equivalence argument).
//
// Semantics:
//   1. At most one scheduled drain exists at any time (scheduledRef), and
//      the drain loop yields at most one continuation frame at a time.
//   2. A full network_update carrying a nodes side supersedes queued node
//      updates OLDER than that snapshot (the snapshot replaces node state
//      wholesale, so their net effect was overwritten anyway); the
//      superseded count is recorded. An edges-only update supersedes
//      nothing on the node side.
//   3. node_update events arriving AFTER the snapshot stay ordered after
//      it (snapshot delivers first in the drain).
//   4. Repeated updates for one id coalesce; distinct ids preserve
//      insertion order.
//   5. Invalid/unidentifiable payloads are counted and dropped at the
//      boundary — they can never grow the queue. (Contract change from
//      the closure queue, which forwarded garbage for the store to
//      reject; the net store state is identical.)
//   6. Pending DISTINCT node ids are bounded. Default derivation
//      (measured on this corpus, Node 24 + jsdom): one folded candidate
//      costs ≈200–400 bytes (5,000 ≈ ≤2 MB, trivial next to the three.js
//      scene) and the drain retires 50 items/frame (5,000 ≈ 100 frames
//      ≈ 1.7 s to fully retire, acceptable recovery for a burst 100×
//      the 50-node default scene). Overflow drops NEW ids only — folds
//      into already-pending ids always proceed.
//   7. Overflow is explicit: stable dropped/coalesced/superseded counters
//      and ONE bounded diagnostic per overflow episode (an episode ends
//      when the queue fully drains). No losslessness is claimed.
//   8. Unmount clears all queued work and scheduling state.
//   9. A throwing handler is contained (report-once channel), never locks
//      processing, and never aborts its batch-mates.
//  10. For ordinary (non-overflowing) traffic the delivered FINAL state is
//      identical to sequential application — locked by an
//      equivalence-versus-reference test.
export const DEFAULT_MAX_PENDING_NODES = 5000
const BATCH_SIZE = 50

interface PendingSnapshot {
  nodes: unknown
  hasNodes: boolean
  edges: unknown
  hasEdges: boolean
}

export function useEventQueue(
  simClient: SimBridgeClient | null,
  handlers: EventQueueHandlers,
  options?: EventQueueOptions,
) {
  const updatesRef = useRef<Map<string, NodeUpdateCandidate>>(new Map())
  const snapshotRef = useRef<PendingSnapshot | null>(null)
  const processingRef = useRef(false)
  const scheduledRef = useRef(false)
  const overflowEpisodeRef = useRef(false)
  const maxPendingRef = useRef(options?.maxPendingNodes ?? DEFAULT_MAX_PENDING_NODES)
  const statsRef = useRef<EventQueueStats>({
    coalesced: 0,
    superseded: 0,
    dropped: 0,
    invalidDropped: 0,
  })
  // Lifetime guard: rAF callbacks scheduled while mounted can fire AFTER
  // unmount, and queued work must never invoke handlers then. Armed on
  // mount, disarmed (and all pending work released) in cleanup;
  // StrictMode's mount→cleanup→mount cycle re-arms correctly.
  const activeRef = useRef(false)

  useEffect(() => {
    activeRef.current = true
    // The Map instance is created once and never reassigned; captured
    // locally so the cleanup closes over the instance itself.
    const updates = updatesRef.current
    return () => {
      activeRef.current = false
      updates.clear()
      snapshotRef.current = null
      overflowEpisodeRef.current = false
    }
  }, [])

  const hasWork = useCallback(
    () => snapshotRef.current !== null || updatesRef.current.size > 0,
    [],
  )

  const processQueue = useCallback(async () => {
    scheduledRef.current = false
    if (processingRef.current) return
    processingRef.current = true
    try {
      while (activeRef.current && hasWork()) {
        let budget = BATCH_SIZE

        const snapshot = snapshotRef.current
        if (snapshot !== null) {
          snapshotRef.current = null
          budget--
          try {
            handlers.setNetwork(
              snapshot.hasNodes ? snapshot.nodes : undefined,
              snapshot.hasEdges ? snapshot.edges : undefined,
            )
          } catch (error) {
            // Handler-error policy (unchanged): contained, reported once
            // through the bounded diagnostic channel, never retried.
            console.error('Event handler failed:', error)
          }
        }

        const updates = updatesRef.current
        for (const [id, candidate] of updates) {
          if (budget <= 0) break
          if (!activeRef.current) return
          updates.delete(id)
          budget--
          try {
            handlers.updateNode(nodeUpdatePayload(candidate))
          } catch (error) {
            console.error('Event handler failed:', error)
          }
        }

        if (!activeRef.current || !hasWork()) break
        // Schedule the next yield frame ONLY while still active with more
        // work queued — an unmount during the LAST handler (or an emptied
        // queue) must not request an extra animation frame.
        await new Promise(resolve => requestAnimationFrame(resolve))
      }
      if (!hasWork()) {
        // The overflow episode ends once the queue fully drains; the next
        // overflow starts a new episode with its own single diagnostic.
        overflowEpisodeRef.current = false
      }
    } finally {
      // Restoration lives in a finally boundary so no exit path — normal,
      // early-return on unmount, or a future throw — can leave the queue
      // permanently locked.
      processingRef.current = false
    }
  }, [handlers, hasWork])

  const schedule = useCallback(() => {
    // At most one scheduled drain at any time: enqueues while a frame is
    // already pending (or a drain is running, which re-checks hasWork)
    // schedule nothing.
    if (scheduledRef.current || processingRef.current) return
    scheduledRef.current = true
    requestAnimationFrame(processQueue)
  }, [processQueue])

  useEffect(() => {
    if (!simClient) return

    const handleNetworkUpdate = (data?: unknown) => {
      if (!activeRef.current) return
      // Null/primitive payloads must not throw, and one malformed side
      // must not discard the other: forward whatever is present and let
      // the store's per-side validation decide (empty arrays stay
      // meaningful and clear their collection).
      if (!data || typeof data !== 'object') return
      const d = data as { nodes?: unknown; edges?: unknown }
      if (d.nodes === undefined && d.edges === undefined) return
      const prior = snapshotRef.current
      const next: PendingSnapshot = prior ?? {
        nodes: undefined,
        hasNodes: false,
        edges: undefined,
        hasEdges: false,
      }
      if (d.nodes !== undefined) {
        next.nodes = d.nodes
        next.hasNodes = true
        // Supersession: this snapshot replaces node state wholesale, so
        // node updates queued BEFORE it can never affect the final state.
        const superseded = updatesRef.current.size
        if (superseded > 0) {
          statsRef.current.superseded += superseded
          updatesRef.current.clear()
        }
      }
      if (d.edges !== undefined) {
        next.edges = d.edges
        next.hasEdges = true
      }
      snapshotRef.current = next
      schedule()
    }

    const handleNodeUpdate = (node?: unknown) => {
      if (!activeRef.current) return
      const candidate = readNodeUpdate(node)
      if (candidate === null) {
        // Invalid/unidentifiable payloads never occupy queue capacity.
        statsRef.current.invalidDropped++
        return
      }
      const updates = updatesRef.current
      const prior = updates.get(candidate.id)
      if (prior !== undefined) {
        // Coalesce latest-valid-wins; refolding an existing id never grows
        // the queue, so it is always allowed — even during overflow.
        updates.set(candidate.id, foldNodeUpdates(prior, candidate))
        statsRef.current.coalesced++
      } else if (updates.size >= maxPendingRef.current) {
        statsRef.current.dropped++
        if (!overflowEpisodeRef.current) {
          overflowEpisodeRef.current = true
          console.error(
            'Event queue overflow: dropping updates for new node ids ' +
              `(pending=${updates.size}, limit=${maxPendingRef.current}). ` +
              'Dropped/coalesced counts are tracked; delivery is NOT lossless under overflow.',
          )
        }
        return
      } else {
        updates.set(candidate.id, candidate)
      }
      schedule()
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
  }, [simClient, handlers, schedule])

  return useMemo(
    () => ({
      stats: statsRef.current,
      pendingCount: () =>
        updatesRef.current.size + (snapshotRef.current !== null ? 1 : 0),
      isProcessing: () => processingRef.current,
    }),
    [],
  )
}
