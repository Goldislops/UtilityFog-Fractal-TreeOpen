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
        // Cleanup lives in FINALLY (adversarial-residual repair): a failing
        // assertion previously skipped the trailing reset, so fast-check's
        // SHRINK iterations ran against a polluted store and the afterEach
        // leak detector masked the real counterexample with its own throw.
        useSceneStore.setState({ nodes: [], edges: [] })
        try {
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
        } finally {
          useSceneStore.setState({ nodes: [], edges: [] })
        }
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
        try {
          const s = useSceneStore.getState()
          s.setNetwork(nodes, edges)
          const first = structuredClone(useSceneStore.getState().nodes)
          const firstEdges = structuredClone(useSceneStore.getState().edges)
          s.setNetwork(nodes, edges)
          expect(useSceneStore.getState().nodes).toEqual(first)
          expect(useSceneStore.getState().edges).toEqual(firstEdges)
        } finally {
          useSceneStore.setState({ nodes: [], edges: [] })
        }
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


describe('property-cleanup isolation contract (adversarial-residual repair)', () => {
  // FAILING-FIRST RECEIPT (probe, not committed): under the previous
  // pattern — trailing reset NOT in finally — a deliberately failing
  // store-mutating property (seed 42, 20 runs) left pollutedEntries > 0
  // across fast-check's shrink iterations and a dirty store after
  // fc.check returned. The finally-based pattern below is the repair;
  // this self-test locks it without failing the suite (fc.check reports
  // instead of throwing).
  it('a FAILING store-mutating property still enters every shrink iteration clean and exits with an empty store', () => {
    useSceneStore.setState({ nodes: [], edges: [] })
    const entryClean: boolean[] = []
    const result = fc.check(
      fc.property(fc.integer({ min: 1, max: 100 }), (n) => {
        entryClean.push(useSceneStore.getState().nodes.length === 0)
        useSceneStore.setState({ nodes: [], edges: [] })
        try {
          useSceneStore
            .getState()
            .updateNode({ id: `iso-${n}`, position: [1, 2, 3], connections: [], status: 'active' })
          expect(n).toBeLessThan(0) // deliberate failure: every iteration throws
        } finally {
          useSceneStore.setState({ nodes: [], edges: [] })
        }
      }),
      { seed: 42, numRuns: 20 },
    )
    expect(result.failed).toBe(true) // the property genuinely failed and shrank
    expect(entryClean.length).toBeGreaterThan(1) // shrink iterations ran
    expect(entryClean.every(Boolean)).toBe(true) // EVERY iteration started isolated
    expect(useSceneStore.getState().nodes).toEqual([]) // nothing escaped fc.check
  })
})

describe('array-container adversaries (custom properties on the LIST itself)', () => {
  // The recorded residual: the ARRAYS carrying node/edge lists can bear
  // custom enumerable/non-index properties, hostile getters on those
  // properties, symbol keys, holes, and proxy wrappers. Contract locked
  // here: only numeric index elements are candidate records; everything
  // else is ignored, never materialized, and never READ. (No total-
  // correctness claim — these are the recorded adversary shapes.)
  const nodeItem = (id: string) => ({ id, position: [1, 2, 3], connections: [], status: 'active' })
  const edgeItem = (id: string) => ({ id, source: 'a', target: 'b', strength: 1 })

  it('harmless custom enumerable properties on the list are ignored and never materialized', () => {
    const nlist: unknown[] = [nodeItem('n1'), nodeItem('n2')]
    ;(nlist as unknown as Record<string, unknown>).smuggled = { payload: 'x' }
    const nout = sanitizeNodeList(nlist, [])
    expect(nout.map(n => n.id)).toEqual(['n1', 'n2'])
    expect(Object.keys(nout)).toEqual(['0', '1']) // fresh array: index keys only
    expect((nout as unknown as Record<string, unknown>).smuggled).toBeUndefined()

    const elist: unknown[] = [edgeItem('e1')]
    ;(elist as unknown as Record<string, unknown>).smuggled = 'y'
    const eout = sanitizeEdgeList(elist, [])
    expect(eout.map(e => e.id)).toEqual(['e1'])
    expect(Object.keys(eout)).toEqual(['0'])
    expect((eout as unknown as Record<string, unknown>).smuggled).toBeUndefined()
  })

  it('a THROWING getter on a custom list property is never touched by either sanitizer', () => {
    let touched = 0
    const arm = (list: unknown[]) =>
      Object.defineProperty(list, 'evil', {
        enumerable: true,
        get(): unknown {
          touched++
          throw new Error('hostile custom list property')
        },
      })
    const nlist = arm([nodeItem('n1')]) as unknown[]
    expect(sanitizeNodeList(nlist, []).map(n => n.id)).toEqual(['n1'])
    const elist = arm([edgeItem('e1')]) as unknown[]
    expect(sanitizeEdgeList(elist, []).map(e => e.id)).toEqual(['e1'])
    expect(touched).toBe(0)
  })

  it('symbol-keyed list properties are never read', () => {
    let touched = 0
    const sym = Symbol('smuggle')
    const nlist: unknown[] = [nodeItem('n1')]
    Object.defineProperty(nlist, sym, {
      enumerable: true,
      get(): unknown {
        touched++
        return 'x'
      },
    })
    expect(sanitizeNodeList(nlist, []).map(n => n.id)).toEqual(['n1'])
    expect(touched).toBe(0)
  })

  it('sparse LIST slots read as absent items: rejected without inventing records, valid items kept', () => {
    const nlist: unknown[] = new Array(3)
    nlist[0] = nodeItem('n1')
    nlist[2] = nodeItem('n2') // hole at index 1
    expect(sanitizeNodeList(nlist, []).map(n => n.id)).toEqual(['n1', 'n2'])
    const elist: unknown[] = new Array(2)
    elist[1] = edgeItem('e1') // hole at index 0
    expect(sanitizeEdgeList(elist, []).map(e => e.id)).toEqual(['e1'])
  })

  it('a proxy-wrapped list is read ONLY through the iterator protocol and index slots (recorded)', () => {
    const touchedKeys: Array<string | symbol> = []
    const proxy = new Proxy([nodeItem('n1')], {
      get(t, k, r) {
        touchedKeys.push(k)
        return Reflect.get(t, k, r)
      },
    })
    expect(sanitizeNodeList(proxy, []).map(n => n.id)).toEqual(['n1'])
    const nonProtocol = touchedKeys.filter(k =>
      typeof k === 'symbol' ? k !== Symbol.iterator : !/^\d+$/.test(k) && k !== 'length',
    )
    // Recorded behavior: no enumeration of non-index keys ever happens —
    // custom properties are structurally unreachable via this read path.
    expect(nonProtocol).toEqual([])
  })

  it('a proxy list whose traps THROW is contained at the delivery boundary (recorded system behavior)', () => {
    const bomb = new Proxy([], {
      get(): unknown {
        throw new Error('hostile list trap')
      },
    })
    // Seam-level recorded behavior: the sanitizer itself surfaces the trap
    // throw (Array.isArray passes; iteration trips the trap)...
    expect(() => sanitizeNodeList(bomb, [])).toThrow('hostile list trap')
    // ...and the STORE action SURFACES it explicitly (Jack delta-audit):
    // setNetwork does NOT swallow the trap — the sanitizer throws before
    // the store's set(), so the throw propagates to the caller AND state
    // is never mutated. The per-delivery containment that decides SYSTEM
    // behavior lives one layer up, in the event queue's handler-error
    // policy (locked by use-event-queue.test.tsx). Asserting toThrow here
    // (not a silent try/catch, which would pass even if the store began
    // swallowing) keeps the surfacing contract under test.
    useSceneStore.setState({ nodes: [], edges: [] })
    expect(() => useSceneStore.getState().setNetwork(bomb, [])).toThrow('hostile list trap')
    expect(useSceneStore.getState().nodes).toEqual([])
    expect(useSceneStore.getState().edges).toEqual([])
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
