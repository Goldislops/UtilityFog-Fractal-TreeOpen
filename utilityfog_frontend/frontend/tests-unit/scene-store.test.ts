// Package V, part 2: the scene-store public contract (useSceneStore).
//
// The store is a module-level zustand singleton; each test starts from an
// explicitly reset state so ordering can never matter. External payloads
// enter as `unknown` exactly as they do from the transport handlers.
import { describe, it, expect, beforeEach } from 'vitest'
import { useSceneStore } from '../src/viz3d/useSceneStore'
import type { NetworkNode, NetworkEdge } from '../src/ws/SimBridgeClient'

const node = (
  id: string,
  position: [number, number, number],
  rest: Partial<NetworkNode> = {},
): NetworkNode => ({
  id,
  position,
  connections: [],
  status: 'active',
  ...rest,
})

const edge = (id: string, source: string, target: string): NetworkEdge => ({
  id,
  source,
  target,
  strength: 1,
})

beforeEach(() => {
  useSceneStore.setState({ nodes: [], edges: [] })
})

describe('useSceneStore.updateNode', () => {
  it('admits a valid node and merges partial updates by id', () => {
    const s = useSceneStore.getState()
    s.updateNode({ id: 'a', position: [1, 2, 3], connections: [], status: 'active' })
    s.updateNode({ id: 'a', status: 'error' })
    expect(useSceneStore.getState().nodes).toEqual([node('a', [1, 2, 3], { status: 'error' })])
  })

  it('rejected updates keep the nodes array reference unchanged (no spurious rerenders)', () => {
    useSceneStore.getState().updateNode({ id: 'a', position: [1, 2, 3], connections: [], status: 'active' })
    const before = useSceneStore.getState().nodes
    useSceneStore.getState().updateNode({ id: 'ghost', status: 'active' }) // unknown, positionless
    useSceneStore.getState().updateNode('not-a-node')
    useSceneStore.getState().updateNode(null)
    expect(useSceneStore.getState().nodes).toBe(before)
  })

  it('survives a hostile payload with a throwing getter; state is unaffected', () => {
    useSceneStore.getState().updateNode({ id: 'a', position: [1, 2, 3], connections: [], status: 'active' })
    const before = useSceneStore.getState().nodes
    const hostile = {
      get id(): unknown {
        throw new Error('hostile id getter')
      },
    }
    expect(() => useSceneStore.getState().updateNode(hostile)).not.toThrow()
    expect(useSceneStore.getState().nodes).toBe(before)
  })

  it('later-valid recovery: a ghost rejected earlier is admitted once it gains a position', () => {
    const s = useSceneStore.getState()
    s.updateNode({ id: 'g', status: 'active' })                 // rejected
    expect(useSceneStore.getState().nodes).toEqual([])
    s.updateNode({ id: 'g', position: [4, 5, 6], connections: [], status: 'active' })
    expect(useSceneStore.getState().nodes.map(n => n.id)).toEqual(['g'])
  })
})

describe('useSceneStore.setNetwork', () => {
  it('replaces both sides wholesale with sanitized input', () => {
    useSceneStore.getState().updateNode({ id: 'old', position: [0, 0, 0], connections: [], status: 'active' })
    useSceneStore.getState().setNetwork(
      [{ id: 'a', position: [1, 1, 1], connections: [], status: 'active' }, { id: 'bad' }],
      [edge('e1', 'a', 'a')],
    )
    const state = useSceneStore.getState()
    expect(state.nodes.map(n => n.id)).toEqual(['a'])
    expect(state.edges).toEqual([edge('e1', 'a', 'a')])
  })

  it('per-side tolerance: a malformed side never discards the valid other side', () => {
    useSceneStore.getState().setNetwork(
      [{ id: 'a', position: [1, 1, 1], connections: [], status: 'active' }],
      [edge('e1', 'a', 'a')],
    )
    useSceneStore.getState().setNetwork(null, [edge('e2', 'a', 'a')])
    expect(useSceneStore.getState().nodes.map(n => n.id)).toEqual(['a'])
    expect(useSceneStore.getState().edges).toEqual([edge('e2', 'a', 'a')])
    useSceneStore.getState().setNetwork([], 'not-edges')
    expect(useSceneStore.getState().nodes).toEqual([])
    expect(useSceneStore.getState().edges).toEqual([edge('e2', 'a', 'a')])
  })

  it('explicit empty arrays remain meaningful and clear both sides', () => {
    useSceneStore.getState().setNetwork(
      [{ id: 'a', position: [1, 1, 1], connections: [], status: 'active' }],
      [edge('e1', 'a', 'a')],
    )
    useSceneStore.getState().setNetwork([], [])
    expect(useSceneStore.getState().nodes).toEqual([])
    expect(useSceneStore.getState().edges).toEqual([])
  })

  it('filters non-object elements out of the edges array (null/string/undefined cannot reach renderers)', () => {
    useSceneStore.getState().setNetwork([], [edge('e1', 'a', 'b'), null, 'junk', undefined, edge('e2', 'b', 'c')])
    expect(useSceneStore.getState().edges).toEqual([edge('e1', 'a', 'b'), edge('e2', 'b', 'c')])
  })

  it('edge OBJECTS with dangling references stay tolerated (renderers skip them)', () => {
    const dangling = { id: 'e-dangling', source: 'nowhere', target: 'nothing', strength: 1 }
    useSceneStore.getState().setNetwork([], [dangling])
    expect(useSceneStore.getState().edges).toEqual([dangling])
  })
})

describe('useSceneStore.updateEdge / clearNetwork', () => {
  it('updateEdge appends new ids and replaces matching ids in place', () => {
    const s = useSceneStore.getState()
    s.updateEdge(edge('e1', 'a', 'b'))
    s.updateEdge(edge('e2', 'b', 'c'))
    s.updateEdge({ ...edge('e1', 'a', 'b'), strength: 9 })
    expect(useSceneStore.getState().edges).toEqual([
      { ...edge('e1', 'a', 'b'), strength: 9 },
      edge('e2', 'b', 'c'),
    ])
  })

  it('clearNetwork empties both sides', () => {
    useSceneStore.getState().setNetwork(
      [{ id: 'a', position: [1, 1, 1], connections: [], status: 'active' }],
      [edge('e1', 'a', 'a')],
    )
    useSceneStore.getState().clearNetwork()
    expect(useSceneStore.getState().nodes).toEqual([])
    expect(useSceneStore.getState().edges).toEqual([])
  })
})

describe('deterministic sequence through the store boundary', () => {
  it('a mixed stream of updates produces one reproducible final state', () => {
    const s = useSceneStore.getState()
    const stream: Array<() => void> = [
      () => s.updateNode({ id: 'a', position: [1, 1, 1], connections: [], status: 'active' }),
      () => s.updateNode({ id: 'b', position: [2, 2, 2], connections: [], status: 'active' }),
      () => s.setNetwork(
        [
          { id: 'b', status: 'error' },                                  // keeps last valid [2,2,2]
          { id: 'c', position: [3, 3, 3], connections: [], status: 'active' },
          { id: 'ghost' },                                               // excluded
        ],
        [edge('e1', 'b', 'c'), null],                                    // null filtered
      ),
      () => s.updateNode({ id: 'c', position: [9, 9, 9] }),
      () => s.updateNode({ id: 'b', position: [0, 0, Number.NaN] }),     // rejected, keeps [2,2,2]
    ]
    stream.forEach(step => step())
    const state = useSceneStore.getState()
    expect(state.nodes.map(n => ({ id: n.id, position: n.position, status: n.status }))).toEqual([
      { id: 'b', position: [2, 2, 2], status: 'error' },
      { id: 'c', position: [9, 9, 9], status: 'active' },
    ])
    expect(state.edges).toEqual([edge('e1', 'b', 'c')])
  })
})

describe('store ownership (Package Y)', () => {
  it('updateNode rejects a NEW node whose non-position getter throws; state unaffected', () => {
    const hostile = {
      id: 'h-new',
      position: [1, 2, 3],
      get status(): unknown {
        throw new Error('hostile status')
      },
    }
    expect(() => useSceneStore.getState().updateNode(hostile)).not.toThrow()
    expect(useSceneStore.getState().nodes).toEqual([])
  })

  it('admitted nodes are materialized: no live getters survive into store state', () => {
    const sneaky = {
      id: 'sneak',
      get position(): unknown {
        return [1, 2, 3]
      },
      connections: [],
      status: 'active',
    }
    useSceneStore.getState().updateNode(sneaky)
    const [stored] = useSceneStore.getState().nodes
    expect(stored).toEqual(node('sneak', [1, 2, 3]))
    expect(stored).not.toBe(sneaky)
    expect(Object.getOwnPropertyDescriptor(stored, 'position')!.get).toBeUndefined()
  })

  it('setNetwork filters edges with invalid property types and throwing getters', () => {
    const hostile = {
      id: 'h',
      source: 'a',
      get target(): unknown {
        throw new Error('hostile target')
      },
    }
    useSceneStore.getState().setNetwork(
      [],
      [edge('ok', 'a', 'b'), { id: 9, source: 'a', target: 'b' }, hostile, { id: 'e', source: 'a' }],
    )
    expect(useSceneStore.getState().edges).toEqual([edge('ok', 'a', 'b')])
  })

  it('admitted edges are materialized owned objects', () => {
    let reads = 0
    const sneakyEdge = {
      id: 'se',
      get source(): unknown {
        reads++
        return 'a'
      },
      target: 'b',
      strength: 1,
    }
    useSceneStore.getState().setNetwork([], [sneakyEdge])
    // Read-count asserted FIRST: vitest's .not.toBe failure-path fallback
    // deep-compares its operands and would read the getter itself,
    // polluting the count (probe-verified: the store path reads exactly
    // once). Ownership is asserted via the property descriptor instead.
    expect(reads).toBe(1)
    const [stored] = useSceneStore.getState().edges
    expect(stored).toEqual(edge('se', 'a', 'b'))
    expect(Object.getOwnPropertyDescriptor(stored, 'source')!.get).toBeUndefined()
  })
})
