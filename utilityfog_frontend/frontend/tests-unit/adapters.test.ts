// Package Z: adaptSimulationData ingress contracts — the previously
// excluded legacy adapter surface.
//
// Legacy fallback contracts under test are PRE-EXISTING and preserved
// byte-exactly where deterministic: falsy ids generate agent_/edge_ index
// ids; agents without a usable position take the documented RANDOM legacy
// fallback; generic nodes without a usable position take the documented
// [0,0,0] legacy fallback (an adapter-dialect contract, distinct from the
// validation boundary, which never invents positions); strength||weight||1
// falsy chains. Ownership (Package Y): admitted records are materialized —
// hostile elements or containers are skipped, never allowed to throw out
// of the adapter.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { adaptSimulationData, generateRandomNetwork } from '../src/viz3d/adapters'

describe('adaptSimulationData — agents dialect', () => {
  it('maps id/position/connections/active with the documented legacy semantics', () => {
    const { nodes } = adaptSimulationData({
      agents: [
        { id: 'a1', position: [1, 2, 3], connections: ['a2'], active: true },
        { id: 'a2', position: [4, 5, 6], connections: [], active: false },
      ],
    })
    expect(nodes).toEqual([
      { id: 'a1', position: [1, 2, 3], connections: ['a2'], status: 'active' },
      { id: 'a2', position: [4, 5, 6], connections: [], status: 'inactive' },
    ])
  })

  it('falsy/non-string ids take the generated agent_<index> id', () => {
    const { nodes } = adaptSimulationData({
      agents: [{ position: [1, 2, 3] }, { id: '', position: [1, 2, 3] }, { id: 7, position: [1, 2, 3] }],
    })
    expect(nodes.map(n => n.id)).toEqual(['agent_0', 'agent_1', 'agent_2'])
  })

  it('unusable positions take the documented random legacy fallback (stubbed deterministic)', () => {
    // Math.random stubbed so the fallback is exact and coverage is
    // deterministic: 0.75 -> 0.75*20-10 = 5 on every axis.
    vi.spyOn(Math, 'random').mockReturnValue(0.75)
    const { nodes } = adaptSimulationData({
      agents: [{ id: 'a' }, { id: 'b', position: 'garbage' }, { id: 'c', position: [1, 2] }],
    })
    expect(nodes.map(n => n.position)).toEqual([
      [5, 5, 5],
      [5, 5, 5],
      [5, 5, 5],
    ])
  })

  it('admitted agents are materialized owned records (no live getters, owned position tuple)', () => {
    let reads = 0
    const supplied = [9, 9, 9]
    const sneaky = {
      id: 'sneak',
      get position(): unknown {
        reads++
        return supplied
      },
      connections: [],
      active: true,
    }
    const { nodes } = adaptSimulationData({ agents: [sneaky] })
    expect(reads).toBe(1)
    expect(nodes[0].position).toEqual([9, 9, 9])
    expect(nodes[0].position).not.toBe(supplied)
    expect(Object.getOwnPropertyDescriptor(nodes[0], 'position')!.get).toBeUndefined()
  })

  it('hostile elements (throwing getters) are skipped without losing the batch', () => {
    const hostile = {
      get id(): unknown {
        throw new Error('hostile agent id')
      },
    }
    const { nodes } = adaptSimulationData({
      agents: [hostile, { id: 'ok', position: [1, 2, 3], connections: [], active: true }],
    })
    expect(nodes.map(n => n.id)).toEqual(['ok'])
  })

  it('a throwing CONTAINER getter is contained (yields no records, no crash)', () => {
    const hostileContainer = {
      get agents(): unknown {
        throw new Error('hostile agents container')
      },
      connections: [{ id: 'e', source: 'a', target: 'b' }],
    }
    expect(() => adaptSimulationData(hostileContainer)).not.toThrow()
    const { edges } = adaptSimulationData(hostileContainer)
    // The poisoned container contributes nothing; well-formed siblings are
    // a separate read and still adapt. (Whether they survive depends on
    // read order — assert the contract that holds: no throw, and the
    // connections read after the poisoned agents read still lands.)
    expect(edges).toEqual([{ id: 'e', source: 'a', target: 'b', strength: 1 }])
  })

  it('non-array truthy containers are skipped safely', () => {
    expect(adaptSimulationData({ agents: 'not-an-array', connections: 42, nodes: {}, edges: 'x' }))
      .toEqual({ nodes: [], edges: [] })
  })
})

describe('adaptSimulationData — connections dialect (shared edge contract, legacy aliases)', () => {
  it('maps source/from and target/to aliases with generated edge_<index> ids', () => {
    const { edges } = adaptSimulationData({
      connections: [
        { source: 'a', target: 'b', strength: 2 },
        { from: 'b', to: 'c', weight: 3 },
      ],
    })
    expect(edges).toEqual([
      { id: 'edge_0', source: 'a', target: 'b', strength: 2 },
      { id: 'edge_1', source: 'b', target: 'c', strength: 3 },
    ])
  })

  it('preserves the strength || weight || 1 falsy chain', () => {
    const { edges } = adaptSimulationData({
      connections: [{ source: 'a', target: 'b', strength: 0, weight: 0 }],
    })
    expect(edges[0].strength).toBe(1)
  })

  it('rejects connections without string endpoints — endpoints are never invented', () => {
    const { edges } = adaptSimulationData({
      connections: [{ source: 'a' }, { target: 'b' }, { source: 1, target: 2 }, {}],
    })
    expect(edges).toEqual([])
  })

  it('null/primitive/hostile elements are skipped without losing valid neighbours', () => {
    const hostile = {
      source: 'a',
      get target(): unknown {
        throw new Error('hostile target')
      },
    }
    const { edges } = adaptSimulationData({
      connections: [null, 42, 'junk', hostile, { source: 'x', target: 'y' }],
    })
    expect(edges).toEqual([{ id: 'edge_4', source: 'x', target: 'y', strength: 1 }])
  })
})

describe('adaptSimulationData — generic nodes/edges dialect', () => {
  it('maps generic nodes, preserving the documented [0,0,0] legacy position fallback', () => {
    const { nodes } = adaptSimulationData({
      nodes: [
        { id: 'n1', position: [1, 2, 3], connections: ['n2'], status: 'error' },
        { id: 'n2' }, // no position: the adapter-dialect fallback applies
      ],
    })
    expect(nodes).toEqual([
      { id: 'n1', position: [1, 2, 3], connections: ['n2'], status: 'error' },
      { id: 'n2', position: [0, 0, 0], connections: [], status: 'active' },
    ])
  })

  it('generic nodes without a usable string id are skipped (nothing to key on)', () => {
    const { nodes } = adaptSimulationData({ nodes: [{ position: [1, 2, 3] }, { id: 9, position: [1, 2, 3] }] })
    expect(nodes).toEqual([])
  })

  it('generic edges require string id/source/target (no generated ids in this dialect)', () => {
    const { edges } = adaptSimulationData({
      edges: [
        { id: 'e1', source: 'a', target: 'b' },
        { source: 'a', target: 'b' }, // no id: rejected
        { id: 'e2', source: 'a', target: 'b', strength: 0 }, // falsy strength -> 1
      ],
    })
    expect(edges).toEqual([
      { id: 'e1', source: 'a', target: 'b', strength: 1 },
      { id: 'e2', source: 'a', target: 'b', strength: 1 },
    ])
  })
})

describe('adaptSimulationData — cross-cutting', () => {
  it('handles malformed nodes and edges together without cross-contamination', () => {
    const { nodes, edges } = adaptSimulationData({
      agents: [null, { id: 'a', position: [1, 1, 1], connections: [], active: true }],
      connections: ['junk', { from: 'a', to: 'a' }],
      nodes: [{ id: 'g', position: [2, 2, 2], connections: [], status: 'active' }, 77],
      edges: [{ id: 'e', source: 'g', target: 'a' }, null],
    })
    expect(nodes.map(n => n.id)).toEqual(['a', 'g'])
    expect(edges.map(e => e.id)).toEqual(['edge_1', 'e'])
  })

  it.each([
    { label: 'null', value: null },
    { label: 'undefined', value: undefined },
    { label: 'primitive', value: 42 },
  ])('$label input adapts to empty collections', ({ value }) => {
    expect(adaptSimulationData(value)).toEqual({ nodes: [], edges: [] })
  })

  it('does not mutate its input (frozen deep fixture)', () => {
    const input = Object.freeze({
      agents: Object.freeze([Object.freeze({ id: 'a', position: Object.freeze([1, 2, 3]), connections: Object.freeze([]), active: true })]),
      connections: Object.freeze([Object.freeze({ source: 'a', target: 'a' })]),
    })
    const snapshot = structuredClone(input)
    const { nodes, edges } = adaptSimulationData(input)
    expect(nodes).toHaveLength(1)
    expect(edges).toHaveLength(1)
    expect(input).toEqual(snapshot)
  })

  it('admits prototype-less containers and elements', () => {
    const el = Object.create(null) as Record<string, unknown>
    el.id = 'p'
    el.position = [1, 2, 3]
    const container = Object.create(null) as Record<string, unknown>
    container.nodes = [el]
    const { nodes } = adaptSimulationData(container)
    expect(nodes).toEqual([{ id: 'p', position: [1, 2, 3], connections: [], status: 'active' }])
  })

  it('duplicate ids pass through the adapter untouched (dedup is the store boundary\'s job)', () => {
    const { nodes } = adaptSimulationData({
      nodes: [
        { id: 'dup', position: [1, 1, 1] },
        { id: 'dup', position: [2, 2, 2] },
      ],
    })
    expect(nodes).toHaveLength(2) // documented: the adapter transforms; sanitizeNodeList dedupes
  })

  it('valid data is structure-equivalent through the adapter', () => {
    const canonical = {
      agents: [{ id: 'a1', position: [1.5, -2, 3e3], connections: ['a2', 'a3'], active: true }],
      connections: [{ id: 'real', source: 'a1', target: 'a2', strength: 0.25 }],
    }
    expect(adaptSimulationData(canonical)).toEqual({
      nodes: [{ id: 'a1', position: [1.5, -2, 3e3], connections: ['a2', 'a3'], status: 'active' }],
      edges: [{ id: 'real', source: 'a1', target: 'a2', strength: 0.25 }],
    })
  })
})

describe('generateRandomNetwork (dev utility)', () => {
  it('generates the requested node count with well-formed, in-bounds records (stubbed deterministic)', () => {
    // A fixed cycling sequence drives every random draw: both status
    // branches, both self-edge outcomes and exact positions are hit
    // deterministically on every run (no coverage wobble).
    const sequence = [0.05, 0.95, 0.5, 0.25, 0.75, 0.6, 0.4, 0.9, 0.1, 0.8]
    let i = 0
    vi.spyOn(Math, 'random').mockImplementation(() => sequence[i++ % sequence.length])
    const { nodes, edges } = generateRandomNetwork(10)
    expect(nodes).toHaveLength(10)
    expect(nodes.map(n => n.id)).toEqual(Array.from({ length: 10 }, (_, i) => `node_${i}`))
    for (const n of nodes) {
      expect(n.position).toHaveLength(3)
      for (const v of n.position) {
        expect(Number.isFinite(v)).toBe(true)
        expect(Math.abs(v)).toBeLessThanOrEqual(20)
      }
      expect(['active', 'inactive']).toContain(n.status)
    }
    // Edges: bounded count, never self-referencing, endpoints always real
    // node ids, strength in [0, 1).
    expect(edges.length).toBeLessThanOrEqual(15)
    const ids = new Set(nodes.map(n => n.id))
    for (const e of edges) {
      expect(e.source).not.toBe(e.target)
      expect(ids.has(e.source)).toBe(true)
      expect(ids.has(e.target)).toBe(true)
      expect(e.strength).toBeGreaterThanOrEqual(0)
      expect(e.strength).toBeLessThan(1)
    }
    // Each generated edge also registered on its source node.
    for (const e of edges) {
      expect(nodes.find(n => n.id === e.source)!.connections).toContain(e.target)
    }
  })
})

describe('Z audit amendments', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('array-shaped agent/generic-node records are rejected — no phantom nodes', () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.75)
    const { nodes } = adaptSimulationData({
      agents: [[1, 2, 3], []],
      nodes: [['n', [1, 2, 3]]],
    })
    expect(nodes).toEqual([])
  })

  it('mixed connection arrays retain only string ids, copied owned', () => {
    const supplied = ['a', 1, null, 'b', { evil: true }]
    const { nodes } = adaptSimulationData({
      agents: [{ id: 'ag', position: [1, 1, 1], connections: supplied, active: true }],
      nodes: [{ id: 'gn', position: [2, 2, 2], connections: supplied }],
    })
    expect(nodes[0].connections).toEqual(['a', 'b'])
    expect(nodes[1].connections).toEqual(['a', 'b'])
    expect(nodes[0].connections).not.toBe(supplied)
    expect(nodes[1].connections).not.toBe(supplied)
  })

  it('invalid generic-node status takes the source-evidenced fallback, never an assertion-lie', () => {
    const { nodes } = adaptSimulationData({
      nodes: [
        { id: 'ok', position: [1, 1, 1], status: 'error' },
        { id: 'bad', position: [1, 1, 1], status: 'weird' },
        { id: 'num', position: [1, 1, 1], status: 42 },
      ],
    })
    expect(nodes.map(n => n.status)).toEqual(['error', 'active', 'active'])
  })
})
