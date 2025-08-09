import { useRef, useMemo, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { InstancedMesh, Matrix4, Color, Object3D } from 'three'
import { NetworkNode } from '../ws/SimBridgeClient'

interface InstancedNodesProps {
  nodes: NetworkNode[]
}

export default function InstancedNodes({ nodes }: InstancedNodesProps) {
  const meshRef = useRef<InstancedMesh>(null)
  const tempObject = useMemo(() => new Object3D(), [])
  const tempColor = useMemo(() => new Color(), [])

  const maxNodes = 1000

  useEffect(() => {
    if (!meshRef.current) return

    const mesh = meshRef.current
    const matrix = new Matrix4()

    // Update instance matrices and colors
    nodes.forEach((node, index) => {
      if (index >= maxNodes) return

      // Set position
      tempObject.position.set(...node.position)
      tempObject.updateMatrix()
      mesh.setMatrixAt(index, tempObject.matrix)

      // Set color based on status
      switch (node.status) {
        case 'active':
          tempColor.setHex(0x10b981)
          break
        case 'inactive':
          tempColor.setHex(0x6b7280)
          break
        case 'error':
          tempColor.setHex(0xef4444)
          break
        default:
          tempColor.setHex(0x3b82f6)
      }
      
      mesh.setColorAt(index, tempColor)
    })

    // Hide unused instances
    for (let i = nodes.length; i < maxNodes; i++) {
      tempObject.position.set(1000, 1000, 1000) // Move off-screen
      tempObject.updateMatrix()
      mesh.setMatrixAt(i, tempObject.matrix)
    }

    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) {
      mesh.instanceColor.needsUpdate = true
    }
  }, [nodes, tempObject, tempColor, maxNodes])

  useFrame((state) => {
    if (!meshRef.current) return

    // Optional: Add subtle animation
    const time = state.clock.getElapsedTime()
    // meshRef.current.rotation.y = time * 0.1
  })

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, maxNodes]}>
      <sphereGeometry args={[0.5, 16, 16]} />
      <meshStandardMaterial />
    </instancedMesh>
  )
}