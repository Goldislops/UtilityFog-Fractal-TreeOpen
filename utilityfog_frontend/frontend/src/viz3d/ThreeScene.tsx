import { useFrame } from '@react-three/fiber'
import InstancedNodes from './InstancedNodes'
import Edges from './Edges'
import { useSceneStore } from './useSceneStore'
import { useEventQueue } from './useEventQueue'
import { SimBridgeClient } from '../ws/SimBridgeClient'

interface ThreeSceneProps {
  simClient: SimBridgeClient | null
}

export default function ThreeScene({ simClient }: ThreeSceneProps) {
  const { nodes, edges, updateNode, setNetwork } = useSceneStore()
  
  useEventQueue(simClient, { updateNode, setNetwork })

  useFrame((state, delta) => {
    // Animation loop for any continuous updates
    // This runs at 60fps and can be used for smooth transitions
  })

  return (
    <>
      <InstancedNodes nodes={nodes} />
      <Edges edges={edges} nodes={nodes} />
    </>
  )
}