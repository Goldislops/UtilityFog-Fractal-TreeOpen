/// <reference types="vite/client" />
// Vite's client type declarations (shipped with the installed vite package)
// type import.meta.env — no compiler flags or casts needed.
import { Suspense, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Grid, Stats } from '@react-three/drei'
import ThreeScene from './ThreeScene'
import { SimBridgeClient } from '../ws/SimBridgeClient'
import {
  CAMERA_PRESETS,
  CAMERA_PRESET_LABELS,
  applyCameraPreset,
  type CameraPresetName,
  type OrbitControlsHandle,
} from './cameraPresets'

interface NetworkView3DProps {
  simClient: SimBridgeClient | null
}

export default function NetworkView3D({ simClient }: NetworkView3DProps) {
  // Package AN-1: view presets. The drei OrbitControls ref exposes the
  // three-stdlib controls instance; the pure seam (cameraPresets) does
  // the repositioning and tolerates the not-yet-mounted interlude.
  const controlsRef = useRef<OrbitControlsHandle | null>(null)
  return (
    <div style={{ flex: 1, position: 'relative' }}>
      {/* Presets are ACTIONS, not state: after any manual orbit a pressed
          indicator would lie, so these carry no aria-pressed (decision
          documented in cameraPresets.ts). */}
      <div className="view-presets" role="group" aria-label="Camera view presets">
        {(Object.keys(CAMERA_PRESETS) as CameraPresetName[]).map(name => (
          <button
            key={name}
            type="button"
            onClick={() => applyCameraPreset(controlsRef.current, name)}
          >
            {CAMERA_PRESET_LABELS[name]}
          </button>
        ))}
      </div>
      <Canvas
        camera={{
          position: [50, 50, 50],
          fov: 75,
          near: 0.1,
          far: 1000,
        }}
        style={{ background: '#0a0a0a' }}
      >
        <Suspense fallback={null}>
          <ambientLight intensity={0.4} />
          <directionalLight position={[10, 10, 5]} intensity={1} />
          <pointLight position={[-10, -10, -5]} intensity={0.5} />
          
          <ThreeScene simClient={simClient} />
          
          <Grid
            args={[100, 100]}
            position={[0, -0.1, 0]}
            cellSize={5}
            cellThickness={0.5}
            cellColor={'#333333'}
            sectionSize={25}
            sectionThickness={1}
            sectionColor={'#555555'}
            fadeDistance={200}
            fadeStrength={1}
          />
          
          <OrbitControls
            ref={controlsRef as never /* drei's ref type; the seam needs only the structural slice */}
            enablePan={true}
            enableZoom={true}
            enableRotate={true}
            maxDistance={200}
            minDistance={10}
          />
        </Suspense>
        
        {import.meta.env.VITE_DEBUG_MODE && <Stats />}
      </Canvas>
    </div>
  )
}