import { useMemo } from 'react'
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

  // Stable handlers identity (evidence: the store actions are stable, but
  // the previous INLINE object changed identity on every render, which
  // resubscribed all three SimBridge channels on every store change).
  const handlers = useMemo(() => ({ updateNode, setNetwork }), [updateNode, setNetwork])

  useEventQueue(simClient, handlers)

  return (
    <>
      <InstancedNodes nodes={nodes} />
      <Edges edges={edges} nodes={nodes} />
    </>
  )
}