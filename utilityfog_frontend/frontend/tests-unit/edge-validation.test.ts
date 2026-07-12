// Package Y: the shared edge ownership contract (edgeValidation.ts) —
// one safely-evaluated materializer used by the legacy adapter, the scene
// store and the NetworkView2D subscription.
//
// Renderer evidence: consumers key on edge.id and index edge.source /
// edge.target against node ids (unmatched ids are skipped — dangling
// REFERENCES are tolerated); strength feeds visual weighting with the
// legacy `|| weight || 1` fallback chain.
import { describe, it, expect } from 'vitest'
import { materializeEdge, sanitizeEdgeList } from '../src/viz3d/edgeValidation'
import type { NetworkEdge } from '../src/ws/SimBridgeClient'

const edge = (id: string, source: string, target: string, strength = 1): NetworkEdge => ({
  id,
  source,
  target,
  strength,
})

describe('materializeEdge', () => {
  it.each([
    { label: 'null', value: null },
    { label: 'undefined', value: undefined },
    { label: 'string', value: 'edge' },
    { label: 'number', value: 42 },
  ])('rejects non-object input: $label', ({ value }) => {
    expect(materializeEdge(value)).toBeNull()
  })

  it('admits a well-formed edge as a NEW owned plain object', () => {
    const input = { id: 'e1', source: 'a', target: 'b', strength: 2 }
    const result = materializeEdge(input)
    expect(result).toEqual(edge('e1', 'a', 'b', 2))
    expect(result).not.toBe(input) // materialized, never the untrusted object
  })

  it('does not retain live getters: each field is read once into owned data', () => {
    let reads = 0
    const sneaky = {
      id: 'e1',
      get source(): unknown {
        reads++
        return 'a'
      },
      target: 'b',
      strength: 1,
    }
    const result = materializeEdge(sneaky)
    expect(result).toEqual(edge('e1', 'a', 'b', 1))
    expect(reads).toBe(1)
    expect(Object.getOwnPropertyDescriptor(result, 'source')!.get).toBeUndefined()
  })

  it.each([
    { label: 'missing id', value: { source: 'a', target: 'b' } },
    { label: 'numeric id', value: { id: 7, source: 'a', target: 'b' } },
    { label: 'missing source', value: { id: 'e', target: 'b' } },
    { label: 'numeric source', value: { id: 'e', source: 1, target: 'b' } },
    { label: 'missing target', value: { id: 'e', source: 'a' } },
    { label: 'null target', value: { id: 'e', source: 'a', target: null } },
  ])('rejects $label — endpoints are never invented or stringified', ({ value }) => {
    expect(materializeEdge(value)).toBeNull()
  })

  it('contains throwing getters on any field', () => {
    for (const field of ['id', 'source', 'target', 'strength']) {
      const hostile: Record<string, unknown> = { id: 'e', source: 'a', target: 'b', strength: 1 }
      Object.defineProperty(hostile, field, {
        enumerable: true,
        get(): unknown {
          throw new Error(`hostile ${field}`)
        },
      })
      expect(materializeEdge(hostile)).toBeNull()
    }
  })

  it('legacy aliases resolve source/from and target/to only when enabled', () => {
    const legacy = { id: 'e', from: 'a', to: 'b', weight: 3 }
    expect(materializeEdge(legacy)).toBeNull() // strict mode: no aliases
    expect(materializeEdge(legacy, { legacyAliases: true })).toEqual(edge('e', 'a', 'b', 3))
    // source/target win over their aliases when both are present.
    expect(
      materializeEdge(
        { id: 'e', source: 's', from: 'f', target: 't', to: 'x', strength: 5, weight: 9 },
        { legacyAliases: true },
      ),
    ).toEqual(edge('e', 's', 't', 5))
  })

  it('fallbackId substitutes only a missing/falsy id (the legacy index contract)', () => {
    expect(materializeEdge({ source: 'a', target: 'b' }, { legacyAliases: true, fallbackId: 'edge_4' }))
      .toEqual(edge('edge_4', 'a', 'b', 1))
    expect(materializeEdge({ id: '', source: 'a', target: 'b' }, { legacyAliases: true, fallbackId: 'edge_4' }))
      .toEqual(edge('edge_4', 'a', 'b', 1)) // '' was falsy under the old || contract
    expect(materializeEdge({ id: 'real', source: 'a', target: 'b' }, { fallbackId: 'edge_4' }))
      .toEqual(edge('real', 'a', 'b', 1))
  })

  it('preserves the strength || weight || 1 fallback chain (falsy and non-finite fall through)', () => {
    const base = { id: 'e', source: 'a', target: 'b' }
    expect(materializeEdge({ ...base, strength: 2 })!.strength).toBe(2)
    expect(materializeEdge({ ...base, strength: 0 })!.strength).toBe(1) // 0 was falsy before
    expect(materializeEdge({ ...base, strength: Number.NaN })!.strength).toBe(1)
    expect(materializeEdge({ ...base })!.strength).toBe(1)
    expect(
      materializeEdge({ ...base, strength: 0, weight: 4 }, { legacyAliases: true })!.strength,
    ).toBe(4)
  })

  it('admits prototype-less objects', () => {
    const bare = Object.create(null) as Record<string, unknown>
    bare.id = 'e'
    bare.source = 'a'
    bare.target = 'b'
    expect(materializeEdge(bare)).toEqual(edge('e', 'a', 'b', 1))
  })

  it('keeps well-formed dangling references (unmatched node ids are the renderer\'s decision)', () => {
    expect(materializeEdge({ id: 'e', source: 'nowhere', target: 'nothing' }))
      .toEqual(edge('e', 'nowhere', 'nothing', 1))
  })
})

describe('sanitizeEdgeList', () => {
  it.each([
    { label: 'null', value: null },
    { label: 'object', value: { length: 1 } },
    { label: 'string', value: 'edges' },
  ])('returns the previous list unchanged (same reference) for non-array: $label', ({ value }) => {
    const previous = [edge('e1', 'a', 'b')]
    expect(sanitizeEdgeList(value, previous)).toBe(previous)
  })

  it('filters nulls, primitives, invalid shapes and hostile getters while admitting valid neighbours', () => {
    const hostile = {
      id: 'h',
      source: 'a',
      get target(): unknown {
        throw new Error('hostile target')
      },
    }
    const result = sanitizeEdgeList(
      [null, 'junk', 42, edge('ok1', 'a', 'b'), { id: 'e', source: 9, target: 'b' }, hostile, edge('ok2', 'b', 'c')],
      [],
    )
    expect(result).toEqual([edge('ok1', 'a', 'b'), edge('ok2', 'b', 'c')])
  })

  it('deduplicates by id, first occurrence wins (matching the node contract)', () => {
    const result = sanitizeEdgeList(
      [edge('e1', 'a', 'b', 1), edge('e2', 'b', 'c', 1), { ...edge('e1', 'x', 'y', 9) }],
      [],
    )
    expect(result).toEqual([edge('e1', 'a', 'b', 1), edge('e2', 'b', 'c', 1)])
  })

  it('does not mutate its input', () => {
    const input = Object.freeze([Object.freeze(edge('e1', 'a', 'b'))]) as unknown as unknown[]
    const previous: NetworkEdge[] = []
    const result = sanitizeEdgeList(input, previous)
    expect(result).toEqual([edge('e1', 'a', 'b')])
    expect(previous).toEqual([])
  })
})
