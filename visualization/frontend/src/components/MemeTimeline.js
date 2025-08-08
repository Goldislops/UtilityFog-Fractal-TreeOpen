import React, { useRef, useEffect, useMemo } from 'react';
import { useSimulation } from '../contexts/SimulationContext';
import * as d3 from 'd3';

const MemeTimeline = () => {
  const svgRef = useRef();
  const {
    timeline,
    memeEvents,
    currentStep,
    config,
    agents
  } = useSimulation();
  
  // Prepare timeline data
  const timelineData = useMemo(() => {
    if (!timeline.memeHistory || timeline.memeHistory.length === 0) {
      return { events: [], timeRange: [0, 100] };
    }
    
    const events = timeline.memeHistory
      .slice(-50) // Last 50 events for performance
      .map((event, index) => ({
        ...event,
        index,
        x: index * 10, // Spacing between events
        type: event.type || 'unknown'
      }));
    
    const timeRange = [
      Math.min(...events.map(e => e.timestamp || 0)),
      Math.max(...events.map(e => e.timestamp || Date.now()))
    ];
    
    return { events, timeRange };
  }, [timeline.memeHistory]);
  
  // Create D3 visualization
  useEffect(() => {
    if (!svgRef.current || timelineData.events.length === 0) return;
    
    const svg = d3.select(svgRef.current);
    const container = svg.node().getBoundingClientRect();
    const width = container.width || 800;
    const height = container.height || 150;
    
    // Clear previous content
    svg.selectAll('*').remove();
    
    // Set up scales
    const xScale = d3.scaleLinear()
      .domain([0, timelineData.events.length - 1])
      .range([40, width - 40]);
    
    const yScale = d3.scaleBand()
      .domain(['infection', 'propagation', 'mutation'])
      .range([20, height - 20])
      .padding(0.2);
    
    // Color scale for different event types
    const colorScale = d3.scaleOrdinal()
      .domain(['infection', 'propagation', 'mutation'])
      .range(['#10b981', '#06b6d4', '#8b5cf6']);
    
    // Create background grid
    svg.append('g')
      .attr('class', 'grid')
      .selectAll('line')
      .data(d3.range(0, timelineData.events.length, 5))
      .enter()
      .append('line')
      .attr('x1', d => xScale(d))
      .attr('x2', d => xScale(d))
      .attr('y1', 0)
      .attr('y2', height)
      .attr('stroke', 'rgba(255, 255, 255, 0.1)')
      .attr('stroke-width', 1);
    
    // Create timeline events
    const eventGroups = svg.selectAll('.event-group')
      .data(timelineData.events)
      .enter()
      .append('g')
      .attr('class', 'event-group')
      .attr('transform', d => `translate(${xScale(d.index)}, ${yScale(d.type) + yScale.bandwidth() / 2})`);
    
    // Event circles
    eventGroups.append('circle')
      .attr('r', 4)
      .attr('fill', d => colorScale(d.type))
      .attr('stroke', 'rgba(255, 255, 255, 0.3)')
      .attr('stroke-width', 1)
      .attr('opacity', 0.8)
      .on('mouseover', function(event, d) {
        // Tooltip functionality
        d3.select(this)
          .transition()
          .duration(200)
          .attr('r', 6)
          .attr('opacity', 1);
        
        // Create tooltip
        const tooltip = svg.append('g')
          .attr('class', 'tooltip')
          .attr('transform', `translate(${xScale(d.index)}, ${yScale(d.type) - 10})`);
        
        const tooltipBg = tooltip.append('rect')
          .attr('x', -50)
          .attr('y', -25)
          .attr('width', 100)
          .attr('height', 20)
          .attr('fill', 'rgba(0, 0, 0, 0.8)')
          .attr('stroke', 'rgba(255, 255, 255, 0.3)')
          .attr('rx', 4);
        
        tooltip.append('text')
          .attr('text-anchor', 'middle')
          .attr('y', -10)
          .attr('fill', 'white')
          .attr('font-size', '10px')
          .text(`${d.type}: ${d.agent_id || d.source_agent || 'unknown'}`);
      })
      .on('mouseout', function(event, d) {
        d3.select(this)
          .transition()
          .duration(200)
          .attr('r', 4)
          .attr('opacity', 0.8);
        
        svg.selectAll('.tooltip').remove();
      });
    
    // Event connections (for propagation events)
    timelineData.events.forEach((event, index) => {
      if (event.type === 'propagation' && event.target_agents) {
        // Draw connection lines
        event.target_agents.forEach(targetAgent => {
          svg.append('line')
            .attr('x1', xScale(index))
            .attr('y1', yScale('propagation') + yScale.bandwidth() / 2)
            .attr('x2', xScale(index) + 15)
            .attr('y2', yScale('infection') + yScale.bandwidth() / 2)
            .attr('stroke', colorScale('propagation'))
            .attr('stroke-width', 1)
            .attr('opacity', 0.4)
            .attr('stroke-dasharray', '2,2');
        });
      }
    });
    
    // Y-axis labels
    svg.selectAll('.axis-label')
      .data(['infection', 'propagation', 'mutation'])
      .enter()
      .append('text')
      .attr('class', 'axis-label')
      .attr('x', 5)
      .attr('y', d => yScale(d) + yScale.bandwidth() / 2)
      .attr('dy', '0.35em')
      .attr('fill', d => colorScale(d))
      .attr('font-size', '10px')
      .attr('font-weight', 'bold')
      .text(d => d.charAt(0).toUpperCase() + d.slice(1));
    
    // Current time indicator
    if (currentStep > 0) {
      const currentX = xScale(Math.min(currentStep / 5, timelineData.events.length - 1));
      svg.append('line')
        .attr('x1', currentX)
        .attr('x2', currentX)
        .attr('y1', 0)
        .attr('y2', height)
        .attr('stroke', '#f59e0b')
        .attr('stroke-width', 2)
        .attr('opacity', 0.8)
        .attr('stroke-dasharray', '5,5');
      
      svg.append('text')
        .attr('x', currentX + 5)
        .attr('y', 15)
        .attr('fill', '#f59e0b')
        .attr('font-size', '10px')
        .attr('font-weight', 'bold')
        .text(`Step ${currentStep}`);
    }
    
  }, [timelineData, currentStep, config]);
  
  // Real-time event indicators
  const recentEvents = useMemo(() => {
    return memeEvents.slice(-5).map((event, index) => ({
      ...event,
      index,
      age: Date.now() - event.createdAt
    }));
  }, [memeEvents]);
  
  return (
    <div className="timeline-container">
      <div className="timeline-header">
        <div className="timeline-title">Meme Propagation Timeline</div>
        <div className="timeline-controls">
          <div className="timeline-legend">
            <div className="legend-item">
              <div className="legend-dot" style={{ backgroundColor: '#10b981' }}></div>
              <span>Infection</span>
            </div>
            <div className="legend-item">
              <div className="legend-dot" style={{ backgroundColor: '#06b6d4' }}></div>
              <span>Propagation</span>
            </div>
            <div className="legend-item">
              <div className="legend-dot" style={{ backgroundColor: '#8b5cf6' }}></div>
              <span>Mutation</span>
            </div>
          </div>
          
          <div className="timeline-stats">
            <span className="stat-item">
              Events: {timeline.memeHistory?.length || 0}
            </span>
            <span className="stat-item">
              Recent: {recentEvents.length}
            </span>
          </div>
        </div>
      </div>
      
      <svg
        ref={svgRef}
        className="timeline-svg"
        width="100%"
        height="100%"
        preserveAspectRatio="xMidYMid meet"
      />
      
      {/* Real-time event feed */}
      {recentEvents.length > 0 && (
        <div className="recent-events-feed">
          {recentEvents.map((event, index) => (
            <div
              key={`recent-${index}`}
              className={`recent-event ${event.type}`}
              style={{
                opacity: Math.max(0.3, 1 - event.age / 10000), // Fade over 10 seconds
                transform: `translateY(${index * -20}px)`
              }}
            >
              <span className="event-type">{event.type}</span>
              <span className="event-agent">{event.agent_id || event.source_agent}</span>
              <span className="event-time">{Math.floor(event.age / 1000)}s ago</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MemeTimeline;