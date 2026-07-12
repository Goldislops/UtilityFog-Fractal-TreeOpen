// Package AA: deterministic property testing over the ingress validators.
//
// fast-check drives generated JSON-like hostile inputs through every
// validator/sanitizer with FIXED RECORDED SEEDS and bounded run counts —
// on any failure fast-check's assertion error reports the seed and
// counterexample path for exact replay.
//
// SCOPE OF CLAIM (narrow, deliberate): these properties demonstrate
// no-throw and invariant behavior over the generated input space and the
// handcrafted adversaries below. They do NOT prove total correctness or
// security.
//
// Seed strategy: FC_SEED overrides the recorded default so the suite can
// be repeated under several fixed seeds; FC_NUM_RUNS overrides the run
// count (local verification used 2000 per central invariant).
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import fc from 'fast-check'
import {
  isValidPosition,
  reconcileNode,
  applyNodeUpdate,
  sanitizeNodeList,
} from '../src/viz3d/nodeValidation'
import { materializeEdge, sanitizeEdgeList } from '../src/viz3d/edgeValidation'
import { adaptSimulationData } from '../src/viz3d/adapters'
import { useSceneStore } from '../src/viz3d/useSceneStore'
import type { NetworkNode } from '../src/ws/SimBridgeClient'

const SEED = Number(process.env.FC_SEED ?? 1720742400)
const NUM_RUNS = Number(process.env.FC_NUM_RUNS ?? 2000)
const PARAMS = { seed: SEED, numRuns: NUM_RUNS }

const EXISTING: NetworkNode = {
  id: 'existing',
  position: [7, 8, 9],
  connections: [],
  status: 'active',
}

const jsonValue = () => fc.jsonValue({ maxDepth: 4 })

// Global-store isolation (audit amendment): the zustand store is a module
// singleton, so every test starts from an ASSERTED empty state and must
// leave it empty — store-mutating predicates reset at the end of every
// property iteration, making cross-test (and cross-iteration) state
// dependence structurally impossible. Verified additionally by
// order-randomized runs (--sequence.shuffle.tests).
const assertStoreEmpty = () => {
  expect(useSceneStore.getState().nodes).toEqual([])
  expect(useSceneStore.getState().edges).toEqual([])
}

beforeEach(() => {
  useSceneStore.setState({ nodes: [], edges: [] })
  assertStoreEmpty()
})

afterEach(() => {
  assertStoreEmpty()
  useSceneStore.setState({ nodes: [], edges: [] })
})

describe(`ingress properties (seed ${SEED}, ${NUM_RUNS} runs per invariant)`, () => {
  it('validators never throw for generated JSON-like values', () => {
    fc.assert(
      fc.property(jsonValue(), (v) => {
        isValidPosition(v)
        reconcileNode(v, undefined)
        reconcileNode(v, EXISTING)
        applyNodeUpdate([EXISTING], v)
        sanitizeNodeList(v, [EXISTING])
        materializeEdge(v)
        materializeEdge(v, { legacyAliases: true, fallbackId: 'edge_0' })
        sanitizeEdgeList(v, [])
        adaptSimulationData(v)
      }),
      PARAMS,
    )
  })

  it('the store never throws and never admits invalid records', () => {
    fc.assert(
      fc.property(jsonValue(), jsonValue(), (a, b) => {
        useSceneStore.setState({ nodes: [], edges: [] })
        const s = useSceneStore.getState()
        s.updateNode(a)
        s.setNetwork(a, b)
        s.updateNode(b)
        const state = useSceneStore.getState()
        for (const n of state.nodes) {
          expect(typeof n.id).toBe('string')
          expect(isValidPosition(n.position)).toBe(true)
          // Materialized: data properties only, no live getters.
          expect(Object.getOwnPropertyDescriptor(n, 'position')!.get).toBeUndefined()
        }
        for (const e of state.edges) {
          expect(typeof e.id).toBe('string')
          expect(typeof e.source).toBe('string')
          expect(typeof e.target).toBe('string')
          expect(Number.isFinite(e.strength)).toBe(true)
        }
        useSceneStore.setState({ nodes: [], edges: [] })
      }),
      PARAMS,
    )
  })

  it('accepted positions are exactly three finite numbers', () => {
    fc.assert(
      fc.property(jsonValue(), (v) => {
        if (isValidPosition(v)) {
          expect(v).toHaveLength(3)
          for (const coord of v) expect(Number.isFinite(coord)).toBe(true)
        }
      }),
      PARAMS,
    )
  })

  it('nodes accepted from scratch carry a usable string id and a valid owned position', () => {
    fc.assert(
      fc.property(jsonValue(), (v) => {
        const result = applyNodeUpdate([], v)
        if (result.length > 0) {
          expect(result).toHaveLength(1)
          expect(typeof result[0].id).toBe('string')
          expect(isValidPosition(result[0].position)).toBe(true)
        }
      }),
      PARAMS,
    )
  })

  it('accepted edges carry usable string id/source/target and finite strength', () => {
    fc.assert(
      fc.property(jsonValue(), fc.boolean(), (v, legacy) => {
        const edge = legacy
          ? materializeEdge(v, { legacyAliases: true, fallbackId: 'edge_0' })
          : materializeEdge(v)
        if (edge !== null) {
          expect(typeof edge.id).toBe('string')
          expect(typeof edge.source).toBe('string')
          expect(typeof edge.target).toBe('string')
          expect(Number.isFinite(edge.strength)).toBe(true)
        }
      }),
      PARAMS,
    )
  })

  it('sanitization is deterministic (same input, same output)', () => {
    // Scope: the deterministic validators. The adapter agents dialect is
    // deliberately excluded — its unusable-position fallback is the
    // documented RANDOM legacy scatter.
    fc.assert(
      fc.property(jsonValue(), (v) => {
        expect(sanitizeNodeList(v, [EXISTING])).toEqual(sanitizeNodeList(v, [EXISTING]))
        expect(sanitizeEdgeList(v, [])).toEqual(sanitizeEdgeList(v, []))
        expect(reconcileNode(v, EXISTING)).toEqual(reconcileNode(v, EXISTING))
        expect(materializeEdge(v)).toEqual(materializeEdge(v))
      }),
      PARAMS,
    )
  })

  it('sanitization does not mutate its input', () => {
    fc.assert(
      fc.property(jsonValue(), (v) => {
        const snapshot = structuredClone(v)
        sanitizeNodeList(v, [EXISTING])
        sanitizeEdgeList(v, [])
        reconcileNode(v, EXISTING)
        materializeEdge(v, { legacyAliases: true, fallbackId: 'edge_0' })
        adaptSimulationData(v)
        expect(v).toEqual(snapshot)
      }),
      PARAMS,
    )
  })

  it('applying the same sanitized network twice is idempotent (wholesale contract)', () => {
    fc.assert(
      fc.property(jsonValue(), jsonValue(), (nodes, edges) => {
        useSceneStore.setState({ nodes: [], edges: [] })
        const s = useSceneStore.getState()
        s.setNetwork(nodes, edges)
        const first = structuredClone(useSceneStore.getState().nodes)
        const firstEdges = structuredClone(useSceneStore.getState().edges)
        s.setNetwork(nodes, edges)
        expect(useSceneStore.getState().nodes).toEqual(first)
        expect(useSceneStore.getState().edges).toEqual(firstEdges)
        useSceneStore.setState({ nodes: [], edges: [] })
      }),
      PARAMS,
    )
  })

  it('malformed updates can never erase the last valid position', () => {
    fc.assert(
      fc.property(jsonValue(), (v) => {
        // Force the arbitrary payload to target the existing node whenever
        // it is object-shaped; every other shape must leave it untouched.
        const targeted =
          v && typeof v === 'object' && !Array.isArray(v) ? { ...(v as object), id: 'existing' } : v
        const result = applyNodeUpdate([EXISTING], targeted)
        const kept = result.find(n => n.id === 'existing')!
        expect(kept).toBeDefined()
        expect(isValidPosition(kept.position)).toBe(true)
      }),
      PARAMS,
    )
  })

  it('output size never exceeds valid input count', () => {
    fc.assert(
      fc.property(jsonValue(), (v) => {
        const nodes = sanitizeNodeList(v, [EXISTING])
        const edges = sanitizeEdgeList(v, [])
        if (Array.isArray(v)) {
          expect(nodes.length).toBeLessThanOrEqual(v.length)
          expect(edges.length).toBeLessThanOrEqual(v.length)
        } else {
          // Non-array input: the previous list is returned unchanged.
          expect(nodes.map(n => n.id)).toEqual(['existing'])
          expect(edges).toEqual([])
        }
        const adapted = adaptSimulationData(v)
        if (v && typeof v === 'object' && !Array.isArray(v)) {
          const container = v as Record<string, unknown>
          const bound = (key: string) =>
            Array.isArray(container[key]) ? (container[key] as unknown[]).length : 0
          expect(adapted.nodes.length).toBeLessThanOrEqual(bound('agents') + bound('nodes'))
          expect(adapted.edges.length).toBeLessThanOrEqual(bound('connections') + bound('edges'))
        } else {
          expect(adapted).toEqual({ nodes: [], edges: [] })
        }
      }),
      PARAMS,
    )
  })
})

describe('handcrafted adversaries (shapes JSON cannot express)', () => {
  const throwingGetter = (field: string): Record<string, unknown> => {
    const obj: Record<string, unknown> = { id: 'x', position: [1, 2, 3], source: 'a', target: 'b' }
    Object.defineProperty(obj, field, {
      enumerable: true,
      get(): unknown {
        throw new Error(`hostile ${field}`)
      },
    })
    return obj
  }

  const adversaries: Array<{ label: string; value: () => unknown }> = [
    { label: 'throwing id getter', value: () => throwingGetter('id') },
    { label: 'throwing position getter', value: () => throwingGetter('position') },
    { label: 'throwing status getter', value: () => throwingGetter('status') },
    { label: 'throwing source getter', value: () => throwingGetter('source') },
    {
      label: 'proxy throwing from get',
      value: () =>
        new Proxy({}, {
          get() {
            throw new Error('hostile get trap')
          },
        }),
    },
    {
      label: 'proxy throwing from has (in operator)',
      value: () =>
        new Proxy({}, {
          has() {
            throw new Error('hostile has trap')
          },
        }),
    },
    {
      label: 'proxy throwing from ownKeys',
      value: () =>
        new Proxy({}, {
          ownKeys() {
            throw new Error('hostile ownKeys trap')
          },
        }),
    },
    {
      label: 'proxy throwing from getOwnPropertyDescriptor',
      value: () =>
        new Proxy({}, {
          getOwnPropertyDescriptor() {
            throw new Error('hostile descriptor trap')
          },
        }),
    },
    { label: 'fully sparse array position', value: () => ({ id: 'x', position: new Array(3) }) },
    {
      label: 'cyclic object',
      value: () => {
        const c: Record<string, unknown> = { id: 'cyc', position: [1, 2, 3] }
        c.self = c
        return c
      },
    },
    {
      label: 'cyclic array in edges slot',
      value: () => {
        const arr: unknown[] = [{ id: 'e', source: 'a', target: 'b' }]
        arr.push(arr)
        return arr
      },
    },
  ]

  it.each(adversaries)('$label crosses no boundary and corrupts no state', ({ value }) => {
    const adversary = value()
    expect(() => {
      isValidPosition(adversary)
      reconcileNode(adversary, undefined)
      reconcileNode(adversary, EXISTING)
      applyNodeUpdate([EXISTING], adversary)
      sanitizeNodeList([adversary], [EXISTING])
      sanitizeNodeList(adversary, [EXISTING])
      materializeEdge(adversary, { legacyAliases: true, fallbackId: 'edge_0' })
      sanitizeEdgeList([adversary], [])
      sanitizeEdgeList(adversary, [])
      adaptSimulationData(adversary)
      adaptSimulationData({ agents: [adversary], connections: [adversary], nodes: [adversary], edges: [adversary] })
    }).not.toThrow()

    useSceneStore.setState({ nodes: [], edges: [] })
    useSceneStore.getState().updateNode(adversary)
    useSceneStore.getState().setNetwork([adversary], [adversary])
    for (const n of useSceneStore.getState().nodes) {
      expect(typeof n.id).toBe('string')
      expect(isValidPosition(n.position)).toBe(true)
    }
    for (const e of useSceneStore.getState().edges) {
      expect(typeof e.source).toBe('string')
      expect(typeof e.target).toBe('string')
    }
    useSceneStore.setState({ nodes: [], edges: [] })
  })

  it('a cyclic node is admitted with only owned fields (cycle never enters the store)', () => {
    const c: Record<string, unknown> = { id: 'cyc', position: [1, 2, 3] }
    c.self = c
    useSceneStore.setState({ nodes: [], edges: [] })
    useSceneStore.getState().updateNode(c)
    const [stored] = useSceneStore.getState().nodes
    expect(stored.id).toBe('cyc')
    expect('self' in stored).toBe(false) // unknown extras dropped by materialization
    expect(() => structuredClone(stored)).not.toThrow() // acyclic, plain data
    useSceneStore.setState({ nodes: [], edges: [] })
  })
})
