import React, { useRef, useEffect, useState, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Text, Line, Sphere, Html } from '@react-three/drei';
import * as THREE from 'three';
import { useSimBridge } from '../contexts/SimBridgeContext';

// Agent Node Component for SimBridge data
const AgentNode = ({ agent, position, onClick, isSelected }) => {
  const meshRef = useRef();
  const [hovered, setHovered] = useState(false);
  
  // Color based on energy and health levels
  const nodeColor = useMemo(() => {
    const energy = agent.energy || 0;
    const health = agent.health || 1;
    
    if (energy > 0.7 && health > 0.8) return '#10b981'; // High energy & health - green
    if (energy > 0.4 && health > 0.5) return '#f59e0b'; // Medium energy & health - orange
    return '#ef4444'; // Low energy or health - red
  }, [agent.energy, agent.health]);
  
  // Size based on active memes
  const nodeSize = useMemo(() => {
    const baseSize = 2;
    const memeCount = agent.active_memes || 0;
    return baseSize + (memeCount * 0.5);
  }, [agent.active_memes]);
  
  // Animation
  useFrame((state) => {
    if (meshRef.current) {
      // Gentle floating animation
      meshRef.current.position.y = position.y + Math.sin(state.clock.elapsedTime * 2 + position.x) * 0.5;
      
      // Scale pulsing based on activity
      const scale = isSelected ? 1.5 : (hovered ? 1.2 : 1.0);
      meshRef.current.scale.setScalar(scale);
      
      // Energy-based glow
      if (meshRef.current.material) {
        const glowIntensity = (agent.energy || 0) * 2;
        meshRef.current.material.emissive.setHex(nodeColor.replace('#', '0x'));
        meshRef.current.material.emissiveIntensity = glowIntensity * 0.3;
      }
    }
  });
  
  return (
    <group position={[position.x, position.y, position.z]}>
      <mesh
        ref={meshRef}
        onClick={() => onClick && onClick(agent)}
        onPointerOver={() => setHovered(true)}
        onPointerOut={() => setHovered(false)}
      >
        <sphereGeometry args={[nodeSize, 16, 16]} />
        <meshStandardMaterial
          color={nodeColor}
          metalness={0.3}
          roughness={0.4}
          transparent
          opacity={0.9}
        />
      </mesh>
      
      {/* Agent Label */}
      {(hovered || isSelected) && (
        <Html
          position={[0, nodeSize + 5, 0]}
          center
          sprite
        >
          <div className="agent-tooltip bg-gray-900 p-2 rounded border text-sm">
            <div className="font-bold text-white">{agent.id}</div>
            <div className="text-gray-300">
              Energy: {(agent.energy || 0).toFixed(2)}
            </div>
            <div className="text-gray-300">
              Health: {(agent.health || 1).toFixed(2)}
            </div>
            <div className="text-gray-300">
              Memes: {agent.active_memes || 0}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
};

// Entanglement Arc Component for SimBridge events
const EntanglementArc = ({ event, agentPositions }) => {
  const lineRef = useRef();
  const [currentOpacity, setCurrentOpacity] = useState(1.0);
  
  const sourcePos = agentPositions[event.data.source];
  const targetPos = agentPositions[event.data.target];
  
  if (!sourcePos || !targetPos) return null;
  
  // Create curved arc points
  const points = useMemo(() => {
    const start = new THREE.Vector3(sourcePos.x, sourcePos.y, sourcePos.z);
    const end = new THREE.Vector3(targetPos.x, targetPos.y, targetPos.z);
    const mid = start.clone().add(end).multiplyScalar(0.5);
    
    // Add curve height based on distance
    const distance = start.distanceTo(end);
    mid.y += distance * 0.3;
    
    // Create smooth curve
    const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
    return curve.getPoints(20);
  }, [sourcePos, targetPos]);
  
  // Color based on entanglement strength
  const arcColor = useMemo(() => {
    const strength = event.data.strength || 0;
    if (strength > 0.7) return '#8b5cf6'; // Strong - purple
    if (strength > 0.4) return '#06b6d4'; // Medium - cyan
    return '#10b981'; // Weak - green
  }, [event.data.strength]);
  
  // Animate the arc (fade based on age)
  useFrame((state) => {
    if (lineRef.current && lineRef.current.material) {
      // Calculate age-based opacity
      const age = Date.now() - event.timestamp;
      const maxAge = 5000; // 5 seconds
      const ageOpacity = Math.max(0, 1 - (age / maxAge));
      
      // Pulsing effect
      const pulse = Math.sin(state.clock.elapsedTime * 4) * 0.3 + 0.7;
      const finalOpacity = ageOpacity * pulse;
      
      lineRef.current.material.opacity = finalOpacity;
      setCurrentOpacity(finalOpacity);
    }
  });
  
  return (
    <Line
      ref={lineRef}
      points={points}
      color={arcColor}
      lineWidth={3}
      transparent
      opacity={currentOpacity}
    />
  );
};

// Meme Spread Visualization
const MemeSpreadArc = ({ event, agentPositions }) => {
  const lineRef = useRef();
  
  const sourcePos = agentPositions[event.data.source];
  const targets = event.data.targets || [];
  
  if (!sourcePos || targets.length === 0) return null;
  
  // Create arcs to all targets
  const arcs = targets.map((targetId, index) => {
    const targetPos = agentPositions[targetId];
    if (!targetPos) return null;
    
    return (
      <Line
        key={`meme-${event.id}-${targetId}-${index}`}
        points={[
          [sourcePos.x, sourcePos.y, sourcePos.z],
          [targetPos.x, targetPos.y, targetPos.z]
        ]}
        color="#f59e0b"
        lineWidth={2}
        transparent
        opacity={0.6}
        dashed
      />
    );
  }).filter(Boolean);
  
  return <>{arcs}</>;
};

// Main Network3D Component for SimBridge
const Network3D = () => {
  const {
    nodes,
    edges,
    currentAgents,
    entanglements,
    memeSpreads,
    isRunning,
    currentStep
  } = useSimBridge();
  
  const [selectedAgent, setSelectedAgent] = useState(null);
  
  // Generate 3D positions for agents (fractal pattern)
  const agentPositions = useMemo(() => {
    const positions = {};
    
    currentAgents.forEach((agent, index) => {
      // Create fractal spiral pattern
      const angle = (index * 2.4) % (2 * Math.PI);
      const level = Math.floor(Math.log(index + 1, 3)) + 1;
      const radius = level * 30;
      
      positions[agent.id] = {
        x: radius * Math.cos(angle) * Math.cos(index * 0.5),
        y: radius * Math.sin(angle) * Math.cos(index * 0.5),
        z: radius * Math.sin(index * 0.5) * 0.3
      };
    });
    
    return positions;
  }, [currentAgents]);
  
  // Handle agent selection
  const handleAgentClick = (agent) => {
    setSelectedAgent(selectedAgent?.id === agent.id ? null : agent);
  };
  
  // Network grid/background
  const NetworkGrid = () => {
    return (
      <group>
        {/* Central grid pattern */}
        <gridHelper
          args={[200, 20, '#333333', '#222222']}
          position={[0, -50, 0]}
          rotation={[0, 0, 0]}
        />
        
        {/* Network connection lines */}
        {edges.map((edge, index) => {
          const sourcePos = agentPositions[edge.source];
          const targetPos = agentPositions[edge.target];
          
          if (!sourcePos || !targetPos) return null;
          
          return (
            <Line
              key={`edge-${index}`}
              points={[
                [sourcePos.x, sourcePos.y, sourcePos.z],
                [targetPos.x, targetPos.y, targetPos.z]
              ]}
              color="#444444"
              lineWidth={1}
              transparent
              opacity={0.3}
            />
          );
        })}
      </group>
    );
  };
  
  return (
    <group>
      {/* Network Grid */}
      <NetworkGrid />
      
      {/* Agent Nodes */}
      {currentAgents.map((agent) => {
        const position = agentPositions[agent.id];
        if (!position) return null;
        
        return (
          <AgentNode
            key={agent.id}
            agent={agent}
            position={position}
            onClick={handleAgentClick}
            isSelected={selectedAgent?.id === agent.id}
          />
        );
      })}
      
      {/* Entanglement Arcs */}
      {entanglements.map((entanglement) => (
        <EntanglementArc
          key={`entanglement-${entanglement.id}`}
          event={entanglement}
          agentPositions={agentPositions}
        />
      ))}
      
      {/* Meme Spread Arcs */}
      {memeSpreads.map((memeSpread) => (
        <MemeSpreadArc
          key={`meme-${memeSpread.id}`}
          event={memeSpread}
          agentPositions={agentPositions}
        />
      ))}
      
      {/* Central Title */}
      <Text
        position={[0, 80, 0]}
        fontSize={8}
        color="#667eea"
        anchorX="center"
        anchorY="middle"
      >
        UtilityFog Fractal Network
      </Text>
      
      {/* Running indicator */}
      {isRunning && (
        <Text
          position={[0, 70, 0]}
          fontSize={4}
          color="#10b981"
          anchorX="center"
          anchorY="middle"
        >
          ● SIMULATION ACTIVE - Step {currentStep}
        </Text>
      )}
      
      {/* Agent Detail Panel */}
      {selectedAgent && (
        <Html position={[60, 40, 0]}>
          <div className="agent-detail-panel bg-gray-900 p-4 rounded-lg border border-gray-600 text-white text-sm">
            <h3 className="font-bold text-lg mb-2">Agent Details</h3>
            <div className="space-y-1">
              <div><strong>ID:</strong> {selectedAgent.id}</div>
              <div><strong>Energy:</strong> {(selectedAgent.energy || 0).toFixed(3)}</div>
              <div><strong>Health:</strong> {(selectedAgent.health || 1).toFixed(3)}</div>
              <div><strong>Active Memes:</strong> {selectedAgent.active_memes || 0}</div>
              <div><strong>Type:</strong> {selectedAgent.type || 'agent'}</div>
              {selectedAgent.role && (
                <div><strong>Role:</strong> {selectedAgent.role}</div>
              )}
            </div>
            <button 
              onClick={() => setSelectedAgent(null)}
              className="mt-3 px-2 py-1 bg-blue-600 rounded text-xs hover:bg-blue-700"
            >
              Close
            </button>
          </div>
        </Html>
      )}
    </group>
  );
};

export default Network3D;