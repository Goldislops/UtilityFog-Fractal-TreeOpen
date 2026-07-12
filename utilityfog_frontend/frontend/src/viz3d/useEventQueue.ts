import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react'
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
  // Deterministic test seam; read once at mount. Bounds TOTAL queued work
  // items (node candidates + snapshots/barriers).
  maxPendingWork?: number
}

export interface EventQueueStats {
  // Stable counters (a live object, mutated in place — a diagnostic/test
  // seam, deliberately not reactive state).
  coalesced: number
  dropped: number
  invalidDropped: number
}

// TYPED ORDERED QUEUE (Package AF, audit redesign). The queue is an
// ORDERED list of typed work items — node-update candidates and
// snapshot/barrier items — delivered strictly in arrival order.
//
// SEQUENTIAL EQUIVALENCE is the load-bearing contract: for every
// non-overflowing trace, the delivered final store state equals plain
// sequential application (locked by a differential harness incl. the two
// audit counterexamples). Consequences:
//   - Snapshots are ORDERING BARRIERS. They never discard earlier queued
//     node updates (a partial snapshot must observe them), they are never
//     merged with each other (a later partial snapshot reconciles against
//     the state the earlier one produced), and node updates never fold
//     across them.
//   - Coalescing happens only within an uninterrupted node-update segment
//     and only when ALGEBRAICALLY SAFE for both the node-exists and
//     node-unknown cases: a candidate may fold into the id's latest
//     queued candidate unless that candidate is POSITIONLESS and the new
//     one carries a position. Sequential application rejects a
//     positionless update on an unknown node WHOLE, so folding its fields
//     into a later creating update would resurrect them (audit CE1);
//     keeping the positionless→positionful transition as two ordered
//     candidates preserves that semantics exactly. Positionless→
//     positionless folds are safe (both merge, or both reject); an
//     anchored (position-bearing) candidate accepts every later fold —
//     the node exists from that candidate on, so per-field latest-valid
//     equals sequential merging, and the anchored candidate also pins the
//     node's creation slot so array append order is preserved.
//   - Invalid/unidentifiable payloads are counted and dropped at the
//     boundary; they never occupy queue capacity.
//
// BOUND: total work items (candidates + snapshots) ≤ maxPendingWork.
// Fold-into-existing never grows the queue and is always allowed; NEW
// items (including snapshots — no barrier evades accounting) are dropped
// under overflow with stable counters and ONE diagnostic per overflow
// episode (an episode ends when the queue fully drains). Overflow is
// explicitly lossy; no losslessness is claimed. Default derivation
// (measured, Node 24 + jsdom): a queued item costs ≈200–400 bytes
// (5,000 ≈ ≤2 MB) and the drain retires 50 items/frame (5,000 ≈ 100
// frames ≈ 1.7 s full recovery) — 100× the default 50-node scene.
//
// SCHEDULING: at most one scheduled rAF drain at any time; the drain
// yields one continuation frame per batch and requests no trailing or
// post-unmount frames.
//
// HANDLERS: delivered through a ref refreshed COMMIT-SYNCHRONOUSLY
// (layout phase) — handler identity changes NEVER resubscribe the
// WebSocket (subscription depends only on the client), and because the
// refresh happens inside the commit itself, no delivery can observe
// stale handlers after a committed rerender. A passive-effect refresh
// would leave a window between commit and effect flush in which an
// already-scheduled rAF drain (paint-aligned, and paint is not ordered
// after passive effects) delivers to the PREVIOUS handlers.
export const DEFAULT_MAX_PENDING_WORK = 5000
const BATCH_SIZE = 50

interface NodeWorkItem {
  kind: 'node'
  id: string
  candidate: NodeUpdateCandidate
}
interface SnapshotWorkItem {
  kind: 'snapshot'
  nodes: unknown
  hasNodes: boolean
  edges: unknown
  hasEdges: boolean
}
type WorkItem = NodeWorkItem | SnapshotWorkItem

export function useEventQueue(
  simClient: SimBridgeClient | null,
  handlers: EventQueueHandlers,
  options?: EventQueueOptions,
) {
  const queueRef = useRef<WorkItem[]>([])
  // Drained items are passed by advancing head (index-stable, so the
  // per-id fold index below never dangles); storage is reclaimed on full
  // drain.
  const headRef = useRef(0)
  // id → index of that id's LATEST queued node item within the current
  // tail segment. Cleared at every barrier and on full drain.
  const lastNodeIndexRef = useRef<Map<string, number>>(new Map())
  const processingRef = useRef(false)
  const scheduledRef = useRef(false)
  const overflowEpisodeRef = useRef(false)
  const maxPendingRef = useRef(options?.maxPendingWork ?? DEFAULT_MAX_PENDING_WORK)
  const statsRef = useRef<EventQueueStats>({
    coalesced: 0,
    dropped: 0,
    invalidDropped: 0,
  })
  // Newest handlers, refreshed inside every commit (layout phase, before
  // any paint/rAF can run) — see HANDLERS note above.
  const handlersRef = useRef(handlers)
  useLayoutEffect(() => {
    handlersRef.current = handlers
  })
  // Lifetime guard: rAF callbacks scheduled while mounted can fire AFTER
  // unmount, and queued work must never invoke handlers then. Armed on
  // mount, disarmed (and all pending work released) in cleanup;
  // StrictMode's mount→cleanup→mount cycle re-arms correctly.
  const activeRef = useRef(false)

  useEffect(() => {
    activeRef.current = true
    const lastNodeIndex = lastNodeIndexRef.current
    return () => {
      activeRef.current = false
      queueRef.current = []
      headRef.current = 0
      lastNodeIndex.clear()
      overflowEpisodeRef.current = false
    }
  }, [])

  const pendingCount = useCallback(() => queueRef.current.length - headRef.current, [])

  const admitOrDrop = useCallback(
    (item: WorkItem): boolean => {
      if (pendingCount() >= maxPendingRef.current) {
        statsRef.current.dropped++
        if (!overflowEpisodeRef.current) {
          overflowEpisodeRef.current = true
          console.error(
            `Event queue overflow: dropping new ${item.kind} work ` +
              `(pending=${pendingCount()}, limit=${maxPendingRef.current}). ` +
              'Dropped/coalesced counts are tracked; delivery is NOT lossless under overflow.',
          )
        }
        return false
      }
      queueRef.current.push(item)
      return true
    },
    [pendingCount],
  )

  const processQueue = useCallback(async () => {
    scheduledRef.current = false
    if (processingRef.current) return
    processingRef.current = true
    try {
      while (activeRef.current && pendingCount() > 0) {
        let budget = BATCH_SIZE
        const queue = queueRef.current
        while (budget > 0 && headRef.current < queue.length) {
          if (!activeRef.current) return
          const item = queue[headRef.current]
          headRef.current++
          budget--
          try {
            if (item.kind === 'node') {
              handlersRef.current.updateNode(nodeUpdatePayload(item.candidate))
            } else {
              handlersRef.current.setNetwork(
                item.hasNodes ? item.nodes : undefined,
                item.hasEdges ? item.edges : undefined,
              )
            }
          } catch (error) {
            // Handler-error policy: contained, reported once through the
            // bounded diagnostic channel, never retried, batch-mates
            // unaffected.
            console.error('Event handler failed:', error)
          }
        }

        if (headRef.current >= queueRef.current.length) {
          // Fully drained: reclaim storage and end any overflow episode.
          queueRef.current = []
          headRef.current = 0
          lastNodeIndexRef.current.clear()
          overflowEpisodeRef.current = false
          break
        }
        if (!activeRef.current) break
        // Schedule the next yield frame ONLY while still active with more
        // work queued — an unmount during the LAST handler (or an emptied
        // queue) must not request an extra animation frame.
        await new Promise(resolve => requestAnimationFrame(resolve))
      }
    } finally {
      // Restoration lives in a finally boundary so no exit path — normal,
      // early-return on unmount, or a future throw — can leave the queue
      // permanently locked.
      processingRef.current = false
    }
  }, [pendingCount])

  const schedule = useCallback(() => {
    // At most one scheduled drain at any time: enqueues while a frame is
    // already pending (or a drain is running, which re-checks the queue)
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
      const admitted = admitOrDrop({
        kind: 'snapshot',
        nodes: d.nodes,
        hasNodes: d.nodes !== undefined,
        edges: d.edges,
        hasEdges: d.edges !== undefined,
      })
      if (admitted) {
        // BARRIER: later node updates start a fresh segment — they must
        // never fold across this snapshot. Earlier queued work is KEPT
        // (the snapshot must observe it).
        lastNodeIndexRef.current.clear()
        schedule()
      }
    }

    const handleNodeUpdate = (node?: unknown) => {
      if (!activeRef.current) return
      const candidate = readNodeUpdate(node)
      if (candidate === null) {
        // Invalid/unidentifiable payloads never occupy queue capacity.
        statsRef.current.invalidDropped++
        return
      }
      const lastIndex = lastNodeIndexRef.current.get(candidate.id)
      if (lastIndex !== undefined && lastIndex >= headRef.current) {
        const target = queueRef.current[lastIndex] as NodeWorkItem
        // Anchored-fold safety rule (see header): never fold a
        // position-bearing candidate into a positionless one.
        const safe = target.candidate.position !== null || candidate.position === null
        if (safe) {
          target.candidate = foldNodeUpdates(target.candidate, candidate)
          statsRef.current.coalesced++
          schedule()
          return
        }
      }
      if (admitOrDrop({ kind: 'node', id: candidate.id, candidate })) {
        lastNodeIndexRef.current.set(candidate.id, queueRef.current.length - 1)
        schedule()
      }
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
  }, [simClient, admitOrDrop, schedule])

  return useMemo(
    () => ({
      stats: statsRef.current,
      pendingCount,
      isProcessing: () => processingRef.current,
    }),
    [pendingCount],
  )
}
