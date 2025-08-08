import React, { useRef, useEffect, useState, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Text, Line, Sphere, Html } from '@react-three/drei';
import * as THREE from 'three';
import { useSimulation } from '../contexts/SimulationContext';

// Agent Node Component
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
    const basSize = 2;
    const memeCount = agent.active_memes || 0;
    return basSize + (memeCount * 0.5);
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

// Entanglement Arc Component
const EntanglementArc = ({ entanglement, positions }) => {
  const lineRef = useRef();
  const [currentOpacity, setCurrentOpacity] = useState(1.0);
  
  const sourcePos = positions[entanglement.source];
  const targetPos = positions[entanglement.target];
  
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
    const strength = entanglement.strength || 0;
    if (strength > 0.7) return '#8b5cf6'; // Strong - purple
    if (strength > 0.4) return '#06b6d4'; // Medium - cyan
    return '#10b981'; // Weak - green
  }, [entanglement.strength]);
  
  // Animate the arc
  useFrame((state) => {
    if (lineRef.current && lineRef.current.material) {
      // Pulsing effect
      const pulse = Math.sin(state.clock.elapsedTime * 4) * 0.3 + 0.7;
      const strength = entanglement.strength || 0;
      const opacity = pulse * strength;
      
      lineRef.current.material.opacity = opacity;
      setCurrentOpacity(opacity);
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

// Main Network3D Component
const Network3D = () => {
  const {
    agents,
    agentPositions,
    entanglements,
    network,
    isRunning
  } = useSimulation();
  
  const [selectedAgent, setSelectedAgent] = useState(null);
  
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
        
        {/* Fractal connection lines for network structure */}
        {network?.edges?.map((edge, index) => {
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
      {agents.map((agent) => {
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
      {entanglements.map((entanglement, index) => (
        <EntanglementArc
          key={`entanglement-${index}-${entanglement.timestamp}`}
          entanglement={entanglement}
          positions={agentPositions}
        />
      ))}
      
      {/* Central Title */}
      <Text
        position={[0, 80, 0]}
        fontSize={8}
        color="#667eea"
        anchorX="center"
        anchorY="middle"
        font="/fonts/Inter-Bold.woff"
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
          ● SIMULATION ACTIVE
        </Text>
      )}
    </group>
  );
};

export default Network3D;