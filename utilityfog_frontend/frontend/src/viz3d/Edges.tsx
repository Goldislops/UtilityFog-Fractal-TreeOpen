import { useMemo } from 'react'
import { Vector3, BufferGeometry, Float32Array } from 'three'
import { NetworkEdge, NetworkNode } from '../ws/SimBridgeClient'

interface EdgesProps {
  edges: NetworkEdge[]
  nodes: NetworkNode[]
}

export default function Edges({ edges, nodes }: EdgesProps) {
  const { geometry, colors } = useMemo(() => {
    const positions: number[] = []
    const colors: number[] = []
    
    const nodeMap = new Map(nodes.map(node => [node.id, node]))

    edges.forEach(edge => {
      const sourceNode = nodeMap.get(edge.source)
      const targetNode = nodeMap.get(edge.target)

      if (sourceNode && targetNode) {
        // Add line positions
        positions.push(...sourceNode.position)
        positions.push(...targetNode.position)

        // Add colors based on edge strength
        const intensity = Math.min(edge.strength, 1)
        const r = intensity
        const g = intensity * 0.5
        const b = intensity * 0.2

        colors.push(r, g, b)
        colors.push(r, g, b)
      }
    })

    const geometry = new BufferGeometry()
    geometry.setAttribute('position', new Float32Array(positions))
    geometry.setAttribute('color', new Float32Array(colors))

    return { geometry, colors }
  }, [edges, nodes])

  if (edges.length === 0) {
    return null
  }

  return (
    <line>
      <primitive object={geometry} />
      <lineBasicMaterial vertexColors transparent opacity={0.6} />
    </line>
  )
}