import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Grid, Stats } from '@react-three/drei'
import ThreeScene from './ThreeScene'
import { SimBridgeClient } from '../ws/SimBridgeClient'

interface NetworkView3DProps {
  simClient: SimBridgeClient | null
}

export default function NetworkView3D({ simClient }: NetworkView3DProps) {
  return (
    <div style={{ flex: 1, position: 'relative' }}>
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