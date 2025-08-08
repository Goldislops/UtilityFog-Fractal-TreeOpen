import React from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid, Stats } from '@react-three/drei';
import { Suspense } from 'react';

import { SimBridgeProvider } from './contexts/SimBridgeContext';
import Network3D from './components/Network3D';
import SimulationControls from './components/SimulationControls';
import StatsDashboard from './components/StatsDashboard';
import LoadingSpinner from './components/LoadingSpinner';

import './App.css';

function App() {
  return (
    <div className="app">
      <SimBridgeProvider>
        {/* Main Layout */}
        <div className="main-container">
          {/* 3D Visualization Canvas */}
          <div className="canvas-container">
            <Canvas
              camera={{ position: [100, 100, 100], fov: 60 }}
              style={{ background: 'radial-gradient(circle, #1a1a2e, #0f0f23)' }}
            >
              <Suspense fallback={null}>
                {/* Lighting */}
                <ambientLight intensity={0.4} />
                <pointLight position={[100, 100, 100]} intensity={1} />
                <pointLight position={[-100, -100, -100]} intensity={0.5} />
                
                {/* Controls */}
                <OrbitControls
                  enablePan={true}
                  enableZoom={true}
                  enableRotate={true}
                  minDistance={10}
                  maxDistance={500}
                />
                
                {/* Grid for reference */}
                <Grid
                  args={[200, 200]}
                  cellSize={10}
                  cellThickness={0.5}
                  cellColor="#333"
                  sectionSize={50}
                  sectionThickness={1}
                  sectionColor="#555"
                  fadeDistance={300}
                  fadeStrength={1}
                  followCamera={false}
                  infiniteGrid={false}
                />
                
                {/* Main 3D Network Visualization */}
                <Network3D />
                
                {/* Performance stats (dev mode) */}
                {process.env.NODE_ENV === 'development' && <Stats />}
              </Suspense>
            </Canvas>
            
            {/* Loading overlay */}
            <LoadingSpinner />
          </div>

          {/* Side Panels */}
          <div className="side-panels">
            {/* Simulation Controls */}
            <div className="panel">
              <SimulationControls />
            </div>

            {/* Statistics Dashboard */}
            <div className="panel">
              <StatsDashboard />
            </div>
          </div>
        </div>

        {/* Header */}
        <div className="header">
          <div className="header-content">
            <h1 className="text-2xl font-bold text-gradient">
              UtilityFog Fractal Network
            </h1>
            <p className="text-sm text-gray-400">
              Real-time 3D visualization of agent interactions, quantum entanglement, and meme propagation
            </p>
          </div>
        </div>
      </SimBridgeProvider>
    </div>
  );
}

export default App;