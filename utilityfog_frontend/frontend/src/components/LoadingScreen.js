import React from 'react';
import { useSimBridge } from '../contexts/SimBridgeContext';

const LoadingScreen = () => {
  const { isRunning, currentAgents, isConnected } = useSimBridge();
  
  // Determine loading state
  const shouldShow = !isConnected || (isRunning && currentAgents.length === 0);
  
  if (!shouldShow) {
    return null;
  }
  
  return (
    <div className="loading-overlay">
      <div className="loading-content">
        {/* Main Spinner */}
        <div className="loading-spinner">
          <div className="spinner-ring"></div>
          <div className="spinner-ring delayed"></div>
          <div className="spinner-ring more-delayed"></div>
        </div>
        
        {/* Loading Text */}
        <div className="loading-text">
          {!isConnected && <div className="loading-message">Connecting to simulation server...</div>}
          {isConnected && isRunning && currentAgents.length === 0 && (
            <div className="loading-message">Initializing simulation...</div>
          )}
        </div>
        
        {/* UtilityFog branding */}
        <div className="loading-brand">
          <div className="brand-logo">⚡</div>
          <div className="brand-text">UtilityFog</div>
          <div className="brand-subtitle">Fractal Network Visualization</div>
        </div>
      </div>
      
      {/* Styles */}
      <style jsx>{`
        .loading-overlay {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: radial-gradient(circle at center, rgba(10, 10, 46, 0.95), rgba(0, 0, 0, 0.98));
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          backdrop-filter: blur(10px);
        }
        
        .loading-content {
          text-align: center;
          color: white;
        }
        
        .loading-spinner {
          position: relative;
          width: 80px;
          height: 80px;
          margin: 0 auto 30px;
        }
        
        .spinner-ring {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          border: 2px solid transparent;
          border-top: 2px solid;
          border-radius: 50%;
          animation: spin 1.2s linear infinite;
        }
        
        .spinner-ring {
          border-top-color: #667eea;
        }
        
        .spinner-ring.delayed {
          width: 65px;
          height: 65px;
          top: 7.5px;
          left: 7.5px;
          border-top-color: #06b6d4;
          animation-duration: 1.8s;
          animation-direction: reverse;
        }
        
        .spinner-ring.more-delayed {
          width: 50px;
          height: 50px;
          top: 15px;
          left: 15px;
          border-top-color: #10b981;
          animation-duration: 2.4s;
        }
        
        .loading-message {
          font-size: 16px;
          color: rgba(255, 255, 255, 0.9);
          margin-bottom: 20px;
          font-weight: 500;
        }
        
        .loading-brand {
          margin-top: 40px;
          opacity: 0.8;
        }
        
        .brand-logo {
          font-size: 48px;
          margin-bottom: 10px;
        }
        
        .brand-text {
          font-size: 24px;
          font-weight: 700;
          margin-bottom: 5px;
        }
        
        .brand-subtitle {
          font-size: 12px;
          color: rgba(255, 255, 255, 0.6);
          font-weight: 300;
        }
        
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default LoadingScreen;