// Foundation suite, part 1: pure viz3d geometry utilities.
//
// These are real contract assertions (exact values, boundary inclusion),
// not smoke checks — they pin the behavior the spatial helpers promise to
// the 3D scene.
import { describe, it, expect } from 'vitest'
import { calculateDistance, clampPosition, findNearbyNodes } from '../src/viz3d/utils'
import type { NetworkNode } from '../src/ws/SimBridgeClient'

const node = (id: string, position: [number, number, number]): NetworkNode => ({
  id,
  position,
  connections: [],
  status: 'active',
})

describe('calculateDistance', () => {
  it.each([
    { a: [0, 0, 0], b: [0, 0, 0], expected: 0 },
    { a: [0, 0, 0], b: [3, 4, 0], expected: 5 },          // classic 3-4-5
    { a: [1, 2, 3], b: [1, 2, 10], expected: 7 },         // single axis
    { a: [-1, -1, -1], b: [1, 1, 1], expected: Math.sqrt(12) },
  ] as Array<{ a: [number, number, number]; b: [number, number, number]; expected: number }>)(
    'distance($a → $b) = $expected',
    ({ a, b, expected }) => {
      expect(calculateDistance(a, b)).toBeCloseTo(expected, 12)
    },
  )

  it('is symmetric', () => {
    const a: [number, number, number] = [2, -7, 0.5]
    const b: [number, number, number] = [-3, 1, 9]
    expect(calculateDistance(a, b)).toBe(calculateDistance(b, a))
  })
})

describe('clampPosition', () => {
  it.each([
    { pos: [0, 0, 0], expected: [0, 0, 0] },              // inside: unchanged
    { pos: [15, -15, 5], expected: [10, -10, 5] },        // clamps both directions
    { pos: [10, -10, 10], expected: [10, -10, 10] },      // bounds are inclusive
  ] as Array<{ pos: [number, number, number]; expected: [number, number, number] }>)(
    'clamp($pos) within ±10 = $expected',
    ({ pos, expected }) => {
      expect(clampPosition(pos, { min: -10, max: 10 })).toEqual(expected)
    },
  )

  it('does not mutate its input', () => {
    const input: [number, number, number] = [99, -99, 0]
    clampPosition(input, { min: -1, max: 1 })
    expect(input).toEqual([99, -99, 0])
  })
})

describe('findNearbyNodes', () => {
  const nodes = [
    node('origin', [0, 0, 0]),
    node('on-radius', [5, 0, 0]),   // distance exactly 5
    node('inside', [1, 1, 1]),
    node('outside', [5.001, 0, 0]),
  ]

  it('includes nodes strictly inside AND exactly on the radius, excludes beyond', () => {
    const found = findNearbyNodes([0, 0, 0], nodes, 5)
    expect(found.map((n) => n.id)).toEqual(['origin', 'on-radius', 'inside'])
  })

  it('returns an empty list when nothing is in range', () => {
    expect(findNearbyNodes([1000, 1000, 1000], nodes, 5)).toEqual([])
  })

  it('does not mutate the node list', () => {
    const before = nodes.map((n) => n.id)
    findNearbyNodes([0, 0, 0], nodes, 5)
    expect(nodes.map((n) => n.id)).toEqual(before)
  })
})
