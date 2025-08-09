import { useEffect, useRef, useState } from 'react'
import { SimBridgeClient, NetworkNode, NetworkEdge } from '../ws/SimBridgeClient'

interface NetworkView2DProps {
  simClient: SimBridgeClient | null
}

export default function NetworkView2D({ simClient }: NetworkView2DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [nodes, setNodes] = useState<NetworkNode[]>([])
  const [edges, setEdges] = useState<NetworkEdge[]>([])

  useEffect(() => {
    if (!simClient) return

    const handleNetworkUpdate = (data: any) => {
      if (data.nodes) setNodes(data.nodes)
      if (data.edges) setEdges(data.edges)
    }

    const handleNodeUpdate = (node: NetworkNode) => {
      setNodes(prev => {
        const index = prev.findIndex(n => n.id === node.id)
        if (index >= 0) {
          const newNodes = [...prev]
          newNodes[index] = node
          return newNodes
        }
        return [...prev, node]
      })
    }

    simClient.on('network_update', handleNetworkUpdate)
    simClient.on('node_update', handleNodeUpdate)

    return () => {
      simClient.off('network_update', handleNetworkUpdate)
      simClient.off('node_update', handleNodeUpdate)
    }
  }, [simClient])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Clear canvas
    ctx.fillStyle = '#1a1a1a'
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    // Draw edges
    ctx.strokeStyle = '#4a5568'
    ctx.lineWidth = 1
    edges.forEach(edge => {
      const sourceNode = nodes.find(n => n.id === edge.source)
      const targetNode = nodes.find(n => n.id === edge.target)
      
      if (sourceNode && targetNode) {
        const sourceX = (sourceNode.position[0] + 10) * 30 + canvas.width / 2
        const sourceY = (sourceNode.position[1] + 10) * 30 + canvas.height / 2
        const targetX = (targetNode.position[0] + 10) * 30 + canvas.width / 2
        const targetY = (targetNode.position[1] + 10) * 30 + canvas.height / 2

        ctx.beginPath()
        ctx.moveTo(sourceX, sourceY)
        ctx.lineTo(targetX, targetY)
        ctx.stroke()
      }
    })

    // Draw nodes
    nodes.forEach(node => {
      const x = (node.position[0] + 10) * 30 + canvas.width / 2
      const y = (node.position[1] + 10) * 30 + canvas.height / 2

      ctx.beginPath()
      ctx.arc(x, y, 6, 0, 2 * Math.PI)
      
      switch (node.status) {
        case 'active':
          ctx.fillStyle = '#10b981'
          break
        case 'inactive':
          ctx.fillStyle = '#6b7280'
          break
        case 'error':
          ctx.fillStyle = '#ef4444'
          break
        default:
          ctx.fillStyle = '#3b82f6'
      }
      
      ctx.fill()
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 2
      ctx.stroke()
    })
  }, [nodes, edges])

  return (
    <div style={{ flex: 1, position: 'relative' }}>
      <canvas
        ref={canvasRef}
        width={800}
        height={600}
        style={{
          width: '100%',
          height: '100%',
          background: '#1a1a1a',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '10px',
          left: '10px',
          color: 'white',
          fontSize: '14px',
        }}
      >
        Nodes: {nodes.length} | Edges: {edges.length}
      </div>
    </div>
  )
}