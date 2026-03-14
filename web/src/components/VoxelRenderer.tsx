import React, { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useStore } from '../store'
import { stateColor, stateOpacity } from '../lib/colors'

const MAX_INSTANCES = 50000
const dummy = new THREE.Object3D()
const color = new THREE.Color()

export default function VoxelRenderer() {
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const { lattice, playing, stepsPerFrame, setMetrics, setRenderData } = useStore()

  const geometry = useMemo(() => new THREE.BoxGeometry(0.9, 0.9, 0.9), [])
  const material = useMemo(() => new THREE.MeshPhongMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.8,
    shininess: 30,
  }), [])

  useFrame(() => {
    if (!lattice || !meshRef.current) return

    // Step if playing
    if (playing) {
      const metricsJson = stepsPerFrame > 1
        ? lattice.step_n(stepsPerFrame)
        : lattice.step()
      useStore.getState().setMetrics(JSON.parse(metricsJson))
    }

    // Get render data: [x, y, z, state, age] per non-void cell
    const data = lattice.render_data()
    const numCells = Math.min(data.length / 5, MAX_INSTANCES)
    const mesh = meshRef.current

    for (let i = 0; i < numCells; i++) {
      const x = data[i * 5]
      const y = data[i * 5 + 1]
      const z = data[i * 5 + 2]
      const state = data[i * 5 + 3]
      const age = data[i * 5 + 4]

      dummy.position.set(x, y, z)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)

      color.setHex(stateColor(state))
      // Age-based brightness for COMPUTE cells
      if (state === 2 && age > 0) {
        const brightness = Math.min(1.5, 1.0 + age / 50.0)
        color.multiplyScalar(brightness)
      }
      mesh.setColorAt(i, color)
    }

    // Hide unused instances
    for (let i = numCells; i < mesh.count; i++) {
      dummy.position.set(0, 0, -9999)
      dummy.scale.set(0, 0, 0)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
    }

    mesh.count = Math.max(numCells, 1)
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true

    useStore.getState().setRenderData(data)
  })

  return (
    <instancedMesh
      ref={meshRef}
      args={[geometry, material, MAX_INSTANCES]}
      frustumCulled={false}
    />
  )
}
