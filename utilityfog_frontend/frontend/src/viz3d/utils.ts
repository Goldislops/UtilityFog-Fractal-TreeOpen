import { Vector3 } from 'three'

export function calculateDistance(pos1: [number, number, number], pos2: [number, number, number]): number {
  const [x1, y1, z1] = pos1
  const [x2, y2, z2] = pos2
  return Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)
}

export function interpolatePosition(
  start: [number, number, number],
  end: [number, number, number],
  t: number
): [number, number, number] {
  return [
    start[0] + (end[0] - start[0]) * t,
    start[1] + (end[1] - start[1]) * t,
    start[2] + (end[2] - start[2]) * t
  ]
}

export function clampPosition(
  position: [number, number, number],
  bounds: { min: number, max: number }
): [number, number, number] {
  return [
    Math.max(bounds.min, Math.min(bounds.max, position[0])),
    Math.max(bounds.min, Math.min(bounds.max, position[1])),
    Math.max(bounds.min, Math.min(bounds.max, position[2]))
  ]
}

export function createSpatialGrid(nodes: any[], gridSize: number = 10) {
  const grid: { [key: string]: any[] } = {}
  
  nodes.forEach(node => {
    const gridX = Math.floor(node.position[0] / gridSize)
    const gridY = Math.floor(node.position[1] / gridSize)
    const gridZ = Math.floor(node.position[2] / gridSize)
    const key = `${gridX},${gridY},${gridZ}`
    
    if (!grid[key]) {
      grid[key] = []
    }
    grid[key].push(node)
  })
  
  return grid
}

export function findNearbyNodes(
  targetPosition: [number, number, number],
  nodes: any[],
  radius: number
): any[] {
  return nodes.filter(node => {
    return calculateDistance(targetPosition, node.position) <= radius
  })
}

export function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

export function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - 2 * (1 - t) * (1 - t)
}

// Performance monitoring utilities
export class PerformanceMonitor {
  private frameCount = 0
  private lastTime = performance.now()
  private fps = 0

  update(): number {
    this.frameCount++
    const currentTime = performance.now()
    
    if (currentTime >= this.lastTime + 1000) {
      this.fps = (this.frameCount * 1000) / (currentTime - this.lastTime)
      this.frameCount = 0
      this.lastTime = currentTime
    }
    
    return this.fps
  }

  getFPS(): number {
    return this.fps
  }
}

export function throttle<T extends any[]>(
  func: (...args: T) => void,
  wait: number
): (...args: T) => void {
  let timeout: number | null = null
  let previous = 0

  return function (...args: T) {
    const now = Date.now()
    const remaining = wait - (now - previous)

    if (remaining <= 0 || remaining > wait) {
      if (timeout) {
        clearTimeout(timeout)
        timeout = null
      }
      previous = now
      func(...args)
    } else if (!timeout) {
      timeout = window.setTimeout(() => {
        previous = Date.now()
        timeout = null
        func(...args)
      }, remaining)
    }
  }
}

export function debounce<T extends any[]>(
  func: (...args: T) => void,
  wait: number
): (...args: T) => void {
  let timeout: number | null = null

  return function (...args: T) {
    if (timeout) clearTimeout(timeout)
    timeout = window.setTimeout(() => func(...args), wait)
  }
}