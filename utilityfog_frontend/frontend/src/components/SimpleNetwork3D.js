import React, { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useSimBridge } from '../contexts/SimBridgeContext';

// Simple Agent Node Component
const AgentNode = ({ agent, position, onClick, isSelected }) => {
  const meshRef = useRef();
  
  // Color based on energy and health levels
  const nodeColor = useMemo(() => {
    const energy = agent.energy || 0;
    const health = agent.health || 1;
    
    if (energy > 0.7 && health > 0.8) return '#10b981'; // High - green
    if (energy > 0.4 && health > 0.5) return '#f59e0b'; // Medium - orange
    return '#ef4444'; // Low - red
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
      
      // Scale pulsing based on selection
      const scale = isSelected ? 1.5 : 1.0;
      meshRef.current.scale.setScalar(scale);
      
      // Energy-based glow
      if (meshRef.current.material) {
        const glowIntensity = (agent.energy || 0) * 2;
        meshRef.current.material.emissive.setHex(parseInt(nodeColor.replace('#', '0x')));
        meshRef.current.material.emissiveIntensity = glowIntensity * 0.3;
      }
    }
  });
  
  return (
    <mesh
      ref={meshRef}
      position={[position.x, position.y, position.z]}
      onClick={() => onClick && onClick(agent)}
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
  );
};

// Simple Entanglement Arc Component
const EntanglementArc = ({ event, agentPositions }) => {
  const lineRef = useRef();
  
  const sourcePos = agentPositions[event.data.source];
  const targetPos = agentPositions[event.data.target];
  
  if (!sourcePos || !targetPos) return null;
  
  // Create line geometry
  const points = useMemo(() => {
    return [
      new THREE.Vector3(sourcePos.x, sourcePos.y, sourcePos.z),
      new THREE.Vector3(targetPos.x, targetPos.y, targetPos.z)
    ];
  }, [sourcePos, targetPos]);
  
  // Color based on strength
  const arcColor = useMemo(() => {
    const strength = event.data.strength || 0;
    if (strength > 0.7) return '#8b5cf6'; // Strong - purple
    if (strength > 0.4) return '#06b6d4'; // Medium - cyan
    return '#10b981'; // Weak - green
  }, [event.data.strength]);
  
  // Animate the arc (fade based on age)
  useFrame((state) => {
    if (lineRef.current && lineRef.current.material) {
      const age = Date.now() - event.timestamp;
      const maxAge = 5000; // 5 seconds
      const ageOpacity = Math.max(0, 1 - (age / maxAge));
      const pulse = Math.sin(state.clock.elapsedTime * 4) * 0.3 + 0.7;
      
      lineRef.current.material.opacity = ageOpacity * pulse;
    }
  });
  
  const geometry = useMemo(() => {
    const geom = new THREE.BufferGeometry().setFromPoints(points);
    return geom;
  }, [points]);
  
  return (
    <line ref={lineRef} geometry={geometry}>
      <lineBasicMaterial color={arcColor} transparent opacity={0.8} />
    </line>
  );
};

// Main Simple Network3D Component
const SimpleNetwork3D = () => {
  const {
    nodes,
    edges,
    currentAgents,
    entanglements,
    isRunning,
    currentStep
  } = useSimBridge();
  
  const [selectedAgent, setSelectedAgent] = React.useState(null);
  
  // Generate 3D positions for agents (fractal pattern)
  const agentPositions = useMemo(() => {
    const positions = {};
    
    currentAgents.forEach((agent, index) => {
      // Create fractal spiral pattern
      const angle = (index * 2.4) % (2 * Math.PI);
      const level = Math.floor(Math.log(index + 1, 3)) + 1;
      const radius = level * 20;
      
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
  
  return (
    <group>
      {/* Grid Helper */}
      <gridHelper args={[200, 20, '#333333', '#222222']} position={[0, -50, 0]} />
      
      {/* Network connection lines */}
      {edges.map((edge, index) => {
        const sourcePos = agentPositions[edge.source];
        const targetPos = agentPositions[edge.target];
        
        if (!sourcePos || !targetPos) return null;
        
        const points = [
          new THREE.Vector3(sourcePos.x, sourcePos.y, sourcePos.z),
          new THREE.Vector3(targetPos.x, targetPos.y, targetPos.z)
        ];
        
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        
        return (
          <line key={`edge-${index}`} geometry={geometry}>
            <lineBasicMaterial color="#444444" transparent opacity={0.3} />
          </line>
        );
      })}
      
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
      
      {/* Title Text */}
      <mesh position={[0, 80, 0]}>
        <textGeometry args={['UtilityFog Network', { font: null, size: 8, height: 1 }]} />
        <meshBasicMaterial color="#667eea" />
      </mesh>
      
      {/* Running indicator */}
      {isRunning && (
        <mesh position={[0, 70, 0]}>
          <textGeometry args={[`● ACTIVE - Step ${currentStep}`, { font: null, size: 4, height: 0.5 }]} />
          <meshBasicMaterial color="#10b981" />
        </mesh>
      )}
    </group>
  );
};

export default SimpleNetwork3D;