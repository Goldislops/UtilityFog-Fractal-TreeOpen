// Package V, part 1: the nodeValidation ingestion-boundary contract,
// tested directly at its exported seams (isValidPosition, reconcileNode,
// applyNodeUpdate, sanitizeNodeList).
//
// External payloads are `unknown` until the module narrows them — these
// tests feed genuinely hostile shapes (sparse arrays, throwing getters,
// prototype-less objects) as well as the documented boundary values.
import { describe, it, expect } from 'vitest'
import {
  isValidPosition,
  reconcileNode,
  applyNodeUpdate,
  sanitizeNodeList,
} from '../src/viz3d/nodeValidation'
import type { NetworkNode } from '../src/ws/SimBridgeClient'

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

describe('isValidPosition', () => {
  it.each([
    { label: 'origin', value: [0, 0, 0], valid: true },
    { label: 'floats and negatives', value: [1.5, -2, 3e10], valid: true },
    { label: 'negative zero', value: [-0, 0, 0], valid: true },
    { label: 'null', value: null, valid: false },
    { label: 'undefined', value: undefined, valid: false },
    { label: 'string', value: 'up-and-left', valid: false },
    { label: 'number', value: 42, valid: false },
    { label: 'plain object', value: { 0: 1, 1: 2, 2: 3, length: 3 }, valid: false },
    { label: 'empty array', value: [], valid: false },
    { label: 'length 2', value: [1, 2], valid: false },
    { label: 'length 4', value: [1, 2, 3, 4], valid: false },
    { label: 'string coordinate', value: [1, 'two', 3], valid: false },
    { label: 'NaN coordinate', value: [1, 2, Number.NaN], valid: false },
    { label: '+Infinity coordinate', value: [1, 2, Number.POSITIVE_INFINITY], valid: false },
    { label: '-Infinity coordinate', value: [Number.NEGATIVE_INFINITY, 0, 0], valid: false },
    { label: 'null coordinate', value: [1, null, 3], valid: false },
  ])('$label → $valid', ({ value, valid }) => {
    expect(isValidPosition(value)).toBe(valid)
  })

  it('rejects fully sparse arrays (Array(3) has length 3 but no coordinates)', () => {
    // every() skips holes, so a naive implementation is vacuously true here.
    expect(isValidPosition(new Array(3))).toBe(false)
  })

  it('rejects a length-3 array with a hole', () => {
    // Built by index assignment: [1, <hole>, 3] without sparse-literal syntax.
    const holed: unknown[] = new Array(3)
    holed[0] = 1
    holed[2] = 3
    expect(isValidPosition(holed)).toBe(false)
  })
})

describe('reconcileNode', () => {
  it('admits an unknown node with a valid position, as supplied', () => {
    const incoming = { id: 'n1', position: [1, 2, 3], connections: [], status: 'active' }
    expect(reconcileNode(incoming, undefined)).toEqual(node('n1', [1, 2, 3]))
  })

  it('merges a partial update over the existing record ({...existing, ...incoming})', () => {
    const existing = node('n1', [1, 2, 3])
    const result = reconcileNode({ id: 'n1', position: [4, 5, 6], status: 'error' }, existing)
    expect(result).toEqual(node('n1', [4, 5, 6], { status: 'error' }))
  })

  it('preserves the LAST VALID position when the update has no usable position', () => {
    const existing = node('n1', [7, 8, 9])
    const result = reconcileNode({ id: 'n1', status: 'error' }, existing)
    expect(result).toEqual(node('n1', [7, 8, 9], { status: 'error' }))
  })

  it.each([
    { label: 'missing position', incoming: { id: 'g' } },
    { label: 'null position', incoming: { id: 'g', position: null } },
    { label: 'NaN position', incoming: { id: 'g', position: [1, 2, Number.NaN] } },
  ])('returns null for an unknown node with $label (no [0,0,0] invented)', ({ incoming }) => {
    expect(reconcileNode(incoming, undefined)).toBeNull()
  })

  it.each([
    { label: 'null', incoming: null },
    { label: 'undefined', incoming: undefined },
    { label: 'string', incoming: 'not-a-node' },
    { label: 'number', incoming: 12 },
  ])('returns null for non-object payload: $label', ({ incoming }) => {
    expect(reconcileNode(incoming, node('n1', [1, 2, 3]))).toBeNull()
  })

  it('admits a prototype-less object carrying a valid position', () => {
    const incoming = Object.create(null) as Record<string, unknown>
    incoming.id = 'proto-free'
    incoming.position = [1, 2, 3]
    incoming.connections = []
    incoming.status = 'active'
    expect(reconcileNode(incoming, undefined)).toEqual(node('proto-free', [1, 2, 3]))
  })

  it('contains a throwing position getter instead of letting it cross the boundary', () => {
    const hostile = {
      id: 'h1',
      get position(): unknown {
        throw new Error('hostile getter')
      },
    }
    expect(reconcileNode(hostile, undefined)).toBeNull()
  })

  it('contains a throwing getter on a non-position field (triggered by merge spread)', () => {
    const hostile = {
      id: 'h2',
      position: [1, 2, 3],
      get status(): unknown {
        throw new Error('hostile getter')
      },
    }
    expect(reconcileNode(hostile, node('h2', [9, 9, 9]))).toBeNull()
  })

  it('does not mutate the existing record or the incoming payload', () => {
    const existing = Object.freeze(node('n1', Object.freeze([1, 2, 3]) as unknown as [number, number, number]))
    const incoming = Object.freeze({ id: 'n1', status: 'error' as const })
    const result = reconcileNode(incoming, existing)
    expect(result).toEqual(node('n1', [1, 2, 3], { status: 'error' }))
    expect(existing).toEqual(node('n1', [1, 2, 3]))
    expect(incoming).toEqual({ id: 'n1', status: 'error' })
  })
})

describe('applyNodeUpdate', () => {
  it.each([
    { label: 'missing id', incoming: { position: [1, 2, 3] } },
    { label: 'numeric id', incoming: { id: 7, position: [1, 2, 3] } },
    { label: 'null payload', incoming: null },
    { label: 'string payload', incoming: 'nope' },
  ])('returns the previous list unchanged (same reference) for $label', ({ incoming }) => {
    const previous = [node('a', [1, 2, 3])]
    expect(applyNodeUpdate(previous, incoming)).toBe(previous)
  })

  it('appends a new valid node and updates an existing one in place (never duplicates)', () => {
    const step1 = applyNodeUpdate([], { id: 'a', position: [1, 2, 3], connections: [], status: 'active' })
    const step2 = applyNodeUpdate(step1, { id: 'b', position: [4, 5, 6], connections: [], status: 'active' })
    const step3 = applyNodeUpdate(step2, { id: 'a', position: [9, 9, 9] })
    expect(step3.map(n => n.id)).toEqual(['a', 'b'])
    expect(step3[0].position).toEqual([9, 9, 9])
  })

  it('returns the previous list (same reference) when reconcile rejects an unknown ghost', () => {
    const previous = [node('a', [1, 2, 3])]
    expect(applyNodeUpdate(previous, { id: 'ghost', status: 'active' })).toBe(previous)
  })

  it('survives a throwing id getter, preserving the previous list', () => {
    const previous = [node('a', [1, 2, 3])]
    const hostile = {
      get id(): unknown {
        throw new Error('hostile id')
      },
    }
    expect(applyNodeUpdate(previous, hostile)).toBe(previous)
  })

  it('does not mutate the previous list on update', () => {
    const original = node('a', [1, 2, 3])
    const previous = Object.freeze([original]) as unknown as NetworkNode[]
    const next = applyNodeUpdate(previous, { id: 'a', status: 'error' })
    expect(next).not.toBe(previous)
    expect(previous[0]).toBe(original)
    expect(original.status).toBe('active')
  })

  it('deterministic sequence: interleaved valid/invalid updates land in a reproducible order', () => {
    // The promised ordering: existing nodes keep their slot, new valid
    // nodes append in arrival order, rejected updates change nothing.
    let list: NetworkNode[] = []
    const feed: unknown[] = [
      { id: 'a', position: [1, 1, 1], connections: [], status: 'active' },
      { id: 'ghost', status: 'active' },                      // rejected: unknown, positionless
      { id: 'b', position: [2, 2, 2], connections: [], status: 'active' },
      { id: 'a', status: 'error' },                           // merge, keeps [1,1,1], keeps slot 0
      { id: 'b', position: [8, 8, 8] },                       // position update in place
      { id: 'c', position: [3, 3, 3], connections: [], status: 'inactive' },
      { id: 'a', position: [1, 2, Number.NaN] },              // rejected: invalid position, 'a' keeps last valid
    ]
    for (const payload of feed) list = applyNodeUpdate(list, payload)
    expect(list.map(n => ({ id: n.id, position: n.position, status: n.status }))).toEqual([
      { id: 'a', position: [1, 1, 1], status: 'error' },
      { id: 'b', position: [8, 8, 8], status: 'active' },
      { id: 'c', position: [3, 3, 3], status: 'inactive' },
    ])
  })
})

describe('sanitizeNodeList', () => {
  it.each([
    { label: 'null', incoming: null },
    { label: 'object', incoming: { length: 1 } },
    { label: 'string', incoming: 'nodes' },
  ])('returns the previous list unchanged (same reference) for non-array: $label', ({ incoming }) => {
    const previous = [node('a', [1, 2, 3])]
    expect(sanitizeNodeList(incoming, previous)).toBe(previous)
  })

  it('is wholesale: nodes absent from the incoming list are dropped', () => {
    const previous = [node('a', [1, 2, 3]), node('b', [4, 5, 6])]
    const result = sanitizeNodeList([{ id: 'b', position: [7, 7, 7], connections: [], status: 'active' }], previous)
    expect(result.map(n => n.id)).toEqual(['b'])
  })

  it('preserves incoming order, keeps first occurrence of duplicate ids', () => {
    const result = sanitizeNodeList(
      [
        { id: 'x', position: [1, 1, 1], connections: [], status: 'active' },
        { id: 'y', position: [2, 2, 2], connections: [], status: 'active' },
        { id: 'x', position: [9, 9, 9] }, // duplicate: first wins
      ],
      [],
    )
    expect(result.map(n => ({ id: n.id, position: n.position }))).toEqual([
      { id: 'x', position: [1, 1, 1] },
      { id: 'y', position: [2, 2, 2] },
    ])
  })

  it('reconciles against previous state: positionless entries keep last valid position', () => {
    const previous = [node('keep', [7, 8, 9])]
    const result = sanitizeNodeList([{ id: 'keep', status: 'error' }], previous)
    expect(result).toEqual([node('keep', [7, 8, 9], { status: 'error' })])
  })

  it('excludes malformed entries while admitting valid neighbours', () => {
    const result = sanitizeNodeList(
      [
        null,
        'junk',
        { id: 'ok', position: [1, 2, 3], connections: [], status: 'active' },
        { id: 42, position: [1, 2, 3] },
        { id: 'ghost' },
        { id: 'holed', position: new Array(3) },
      ],
      [],
    )
    expect(result.map(n => n.id)).toEqual(['ok'])
  })

  it('skips entries with throwing getters without losing the rest of the batch', () => {
    const hostileId = {
      get id(): unknown {
        throw new Error('hostile id')
      },
    }
    const hostilePosition = {
      id: 'hp',
      get position(): unknown {
        throw new Error('hostile position')
      },
    }
    const result = sanitizeNodeList(
      [hostileId, { id: 'ok', position: [1, 2, 3], connections: [], status: 'active' }, hostilePosition],
      [],
    )
    expect(result.map(n => n.id)).toEqual(['ok'])
  })

  it('does not mutate the previous list', () => {
    const previous = Object.freeze([node('a', [1, 2, 3])]) as unknown as NetworkNode[]
    const result = sanitizeNodeList([{ id: 'b', position: [1, 1, 1], connections: [], status: 'active' }], previous)
    expect(result.map(n => n.id)).toEqual(['b'])
    expect(previous.map(n => n.id)).toEqual(['a'])
  })
})

describe('node materialization (ownership contract — Package Y)', () => {
  it('never returns the untrusted incoming object itself, even for new nodes', () => {
    const incoming = { id: 'own1', position: [1, 2, 3], connections: [], status: 'active' }
    const result = reconcileNode(incoming, undefined)
    expect(result).toEqual(node('own1', [1, 2, 3]))
    expect(result).not.toBe(incoming)
  })

  it('does not retain live getters on admitted NEW nodes (each field read exactly once)', () => {
    let positionReads = 0
    let statusReads = 0
    const sneaky = {
      id: 'sneak',
      get position(): unknown {
        positionReads++
        return [1, 2, 3]
      },
      connections: [],
      get status(): unknown {
        statusReads++
        return 'active'
      },
    }
    const result = reconcileNode(sneaky, undefined)!
    expect(result).toEqual(node('sneak', [1, 2, 3]))
    expect(positionReads).toBe(1)
    expect(statusReads).toBe(1)
    expect(Object.getOwnPropertyDescriptor(result, 'position')!.get).toBeUndefined()
    expect(Object.getOwnPropertyDescriptor(result, 'status')!.get).toBeUndefined()
  })

  it('returns an owned position tuple, never the caller-supplied array', () => {
    const suppliedPosition = [4, 5, 6]
    const result = reconcileNode(
      { id: 'own2', position: suppliedPosition, connections: [], status: 'active' },
      undefined,
    )!
    expect(result.position).toEqual([4, 5, 6])
    expect(result.position).not.toBe(suppliedPosition)
    suppliedPosition[0] = 999 // later mutation of the input cannot reach the store
    expect(result.position).toEqual([4, 5, 6])
  })

  it('contains a throwing getter on a non-position field when existing is undefined (new node)', () => {
    const hostile = {
      id: 'h-new',
      position: [1, 2, 3],
      get status(): unknown {
        throw new Error('hostile status on new node')
      },
    }
    expect(reconcileNode(hostile, undefined)).toBeNull()
  })

  it('owns only renderer-consumed fields — unknown extras are dropped, not carried', () => {
    const incoming = {
      id: 'own3',
      position: [1, 2, 3],
      connections: [],
      status: 'active',
      junk: { deep: 'payload' },
    }
    const result = reconcileNode(incoming, undefined)!
    expect('junk' in result).toBe(false)
  })
})

describe('node contract hardening (Jack audit amendment)', () => {
  it.each([
    { label: 'numeric id', incoming: { id: 7, position: [1, 2, 3] } },
    { label: 'empty-string id', incoming: { id: '', position: [1, 2, 3] } },
  ])('rejects $label at every public admission seam', ({ incoming }) => {
    expect(reconcileNode(incoming, undefined)).toBeNull()
    const previous = [node('a', [1, 2, 3])]
    expect(applyNodeUpdate(previous, incoming)).toBe(previous)
    expect(sanitizeNodeList([incoming], [])).toEqual([])
  })

  it('discards an invalid status as absent on a new node (documented rule, no assertion-lie)', () => {
    const result = reconcileNode({ id: 'n', position: [1, 2, 3], status: 'weird' }, undefined)!
    expect(result.id).toBe('n')
    expect(result.status).toBeUndefined()
  })

  it('an invalid incoming status never clobbers a valid existing one', () => {
    const existing = node('n', [1, 2, 3], { status: 'error' })
    const result = reconcileNode({ id: 'n', status: 'nonsense' }, existing)!
    expect(result.status).toBe('error')
  })

  it.each(['active', 'inactive', 'error'] as const)('valid status %s passes', (status) => {
    expect(reconcileNode({ id: 'n', position: [1, 2, 3], status }, undefined)!.status).toBe(status)
  })

  it('mixed connection arrays retain only strings, copied into an owned array', () => {
    const suppliedConnections = ['a', 1, null, 'b', { evil: true }, 'c']
    const result = reconcileNode(
      { id: 'n', position: [1, 2, 3], connections: suppliedConnections },
      undefined,
    )!
    expect(result.connections).toEqual(['a', 'b', 'c'])
    expect(result.connections).not.toBe(suppliedConnections)
  })

  it('non-array connections are treated as absent (existing value survives)', () => {
    const existing = node('n', [1, 2, 3], { connections: ['keep'] })
    const result = reconcileNode({ id: 'n', connections: 'garbage' }, existing)!
    expect(result.connections).toEqual(['keep'])
  })

  it('a hostile getter inside a connections ELEMENT is contained', () => {
    const hostileElement = {}
    Object.defineProperty(hostileElement, 'toString', {
      get(): unknown {
        throw new Error('hostile element')
      },
    })
    const result = reconcileNode(
      { id: 'n', position: [1, 2, 3], connections: ['ok', hostileElement] },
      undefined,
    )!
    expect(result.connections).toEqual(['ok'])
  })
})

describe('referential stability (Jack audit amendment)', () => {
  const EXISTING = node('stable', [1, 2, 3], { status: 'active', connections: ['x'] })

  it('reconcileNode returns the EXISTING object when every owned field is unchanged', () => {
    const identical = { id: 'stable', position: [1, 2, 3], status: 'active', connections: ['x'] }
    expect(reconcileNode(identical, EXISTING)).toBe(EXISTING)
  })

  it('a positionless partial that changes nothing returns the existing reference', () => {
    expect(reconcileNode({ id: 'stable', status: 'active' }, EXISTING)).toBe(EXISTING)
  })

  it('changed fields still produce a NEW owned reference', () => {
    const changed = reconcileNode({ id: 'stable', status: 'error' }, EXISTING)!
    expect(changed).not.toBe(EXISTING)
    expect(changed.status).toBe('error')
    const moved = reconcileNode({ id: 'stable', position: [9, 9, 9] }, EXISTING)!
    expect(moved).not.toBe(EXISTING)
    expect(moved.position).toEqual([9, 9, 9])
  })

  it('applyNodeUpdate returns the previous ARRAY reference for a no-op update', () => {
    const previous = [EXISTING]
    expect(applyNodeUpdate(previous, { id: 'stable', status: 'active' })).toBe(previous)
  })

  it('sanitizeNodeList returns the previous array reference when nothing changed', () => {
    const previous = [EXISTING]
    const wholesale = [{ id: 'stable', position: [1, 2, 3], status: 'active', connections: ['x'] }]
    expect(sanitizeNodeList(wholesale, previous)).toBe(previous)
  })

  it('sanitizeNodeList produces a new array when membership or order changes', () => {
    const previous = [EXISTING]
    const reduced = sanitizeNodeList([], previous)
    expect(reduced).not.toBe(previous)
    expect(reduced).toEqual([])
  })
})
