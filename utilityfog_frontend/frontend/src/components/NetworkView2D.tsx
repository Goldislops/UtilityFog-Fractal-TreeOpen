import React, { useRef, useEffect, useState } from 'react';
import { InitStateMessage } from '../ws/SimBridgeClient';

interface NetworkView2DProps {
  initState?: InitStateMessage;
  agentUpdates: Map<string, any>;
  width?: number;
  height?: number;
}

interface Node {
  id: string;
  x: number;
  y: number;
  energy?: number;
  health?: number;
  active_memes?: number;
  [key: string]: any;
}

interface Edge {
  source: string;
  target: string;
}

const NetworkView2D: React.FC<NetworkView2DProps> = ({ 
  initState, 
  agentUpdates,
  width = 600, 
  height = 400 
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);

  // Initialize nodes and edges from initState
  useEffect(() => {
    if (initState?.data.nodes && initState?.data.edges) {
      console.log('🎯 Initializing network view with', initState.data.nodes.length, 'nodes');
      
      // Create initial node positions in a circular layout
      const initialNodes: Node[] = initState.data.nodes.map((node, index) => {
        const angle = (index / initState.data.nodes.length) * 2 * Math.PI;
        const radius = Math.min(width, height) * 0.3;
        const centerX = width / 2;
        const centerY = height / 2;
        
        return {
          ...node,
          x: centerX + radius * Math.cos(angle),
          y: centerY + radius * Math.sin(angle),
          energy: node.energy || 0.5,
          health: node.health || 1.0,
          active_memes: node.active_memes || 0
        };
      });
      
      setNodes(initialNodes);
      setEdges(initState.data.edges);
    }
  }, [initState, width, height]);

  // Apply agent updates
  useEffect(() => {
    if (agentUpdates.size > 0) {
      setNodes(prevNodes => 
        prevNodes.map(node => {
          const update = agentUpdates.get(node.id);
          if (update) {
            return { ...node, ...update };
          }
          return node;
        })
      );
    }
  }, [agentUpdates]);

  // Render canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear canvas
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, width, height);

    // Draw edges
    ctx.strokeStyle = '#374151';
    ctx.lineWidth = 1;
    edges.forEach(edge => {
      const sourceNode = nodes.find(n => n.id === edge.source);
      const targetNode = nodes.find(n => n.id === edge.target);
      
      if (sourceNode && targetNode) {
        ctx.beginPath();
        ctx.moveTo(sourceNode.x, sourceNode.y);
        ctx.lineTo(targetNode.x, targetNode.y);
        ctx.stroke();
      }
    });

    // Draw nodes
    nodes.forEach(node => {
      // Node color based on energy and health
      const energy = node.energy || 0;
      const health = node.health || 1;
      
      let fillColor: string;
      if (energy > 0.7 && health > 0.8) {
        fillColor = '#10b981'; // High - green
      } else if (energy > 0.4 && health > 0.5) {
        fillColor = '#f59e0b'; // Medium - orange
      } else {
        fillColor = '#ef4444'; // Low - red
      }

      // Node size based on memes
      const baseRadius = 8;
      const memeCount = node.active_memes || 0;
      const radius = baseRadius + (memeCount * 2);

      // Draw node
      ctx.fillStyle = fillColor;
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fill();

      // Draw node border
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Draw node label
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(node.id.slice(0, 8), node.x, node.y - radius - 5);

      // Draw stats
      ctx.font = '8px monospace';
      ctx.fillStyle = '#9ca3af';
      ctx.fillText(
        `E:${energy.toFixed(2)} H:${health.toFixed(2)}`, 
        node.x, 
        node.y + radius + 15
      );
    });

    // Draw legend
    ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
    ctx.fillRect(10, 10, 180, 80);
    
    ctx.fillStyle = '#ffffff';
    ctx.font = '12px monospace';
    ctx.textAlign = 'left';
    ctx.fillText('Network Legend:', 15, 25);
    
    // Energy levels
    const legendItems = [
      { color: '#10b981', text: 'High Energy (>0.7)' },
      { color: '#f59e0b', text: 'Med Energy (0.4-0.7)' },
      { color: '#ef4444', text: 'Low Energy (<0.4)' }
    ];
    
    legendItems.forEach((item, index) => {
      const y = 40 + (index * 15);
      ctx.fillStyle = item.color;
      ctx.beginPath();
      ctx.arc(20, y, 4, 0, 2 * Math.PI);
      ctx.fill();
      
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px monospace';
      ctx.fillText(item.text, 30, y + 3);
    });

  }, [nodes, edges, width, height]);

  const nodeCount = nodes.length;
  const edgeCount = edges.length;
  const avgEnergy = nodes.reduce((sum, n) => sum + (n.energy || 0), 0) / Math.max(nodeCount, 1);

  return (
    <div style={{
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      border: '1px solid #374151',
      borderRadius: '8px',
      padding: '16px'
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '12px'
      }}>
        <h3 style={{
          margin: 0,
          fontSize: '16px',
          fontWeight: '600',
          color: '#ffffff'
        }}>
          Network View 2D
        </h3>
        <div style={{
          fontSize: '12px',
          color: '#9ca3af',
          fontFamily: 'monospace'
        }}>
          Nodes: {nodeCount} | Edges: {edgeCount} | Avg Energy: {avgEnergy.toFixed(2)}
        </div>
      </div>
      
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        style={{
          border: '1px solid #4b5563',
          borderRadius: '4px',
          backgroundColor: '#000000'
        }}
      />
      
      {nodeCount === 0 && (
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          color: '#6b7280',
          fontSize: '14px',
          textAlign: 'center'
        }}>
          No network data yet.<br/>
          Start a simulation to see the network visualization.
        </div>
      )}
    </div>
  );
};

export default NetworkView2D;