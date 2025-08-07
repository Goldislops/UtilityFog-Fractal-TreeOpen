"""
Specialized Loggers for UtilityFog Simulation Testing

This module provides specialized logging capabilities for different aspects
of the simulation, with particular focus on quantum myelin interactions.
"""

import time
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class LogEntry:
    """Structure for a single log entry."""
    timestamp: float
    level: str
    component: str
    message: str
    data: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "component": self.component,
            "message": self.message,
            "data": self.data or {}
        }


class QuantumMyelinLogger:
    """Specialized logger for quantum myelin interactions and entanglement events."""
    
    def __init__(self):
        """Initialize the quantum myelin logger."""
        self.logs: List[LogEntry] = []
        self.entanglement_events: List[Dict[str, Any]] = []
        self.meme_infection_events: List[Dict[str, Any]] = []
        self.meme_propagation_events: List[Dict[str, Any]] = []
        
        # Statistics tracking
        self.stats = {
            "total_entanglements": 0,
            "total_infections": 0,
            "total_propagations": 0,
            "agent_entanglement_count": defaultdict(int),
            "meme_infection_count": defaultdict(int),
            "entanglement_strength_sum": 0.0,
            "average_entanglement_strength": 0.0
        }
    
    def log_entanglement(
        self,
        agent_a_id: str,
        agent_b_id: str,
        entanglement_strength: float,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log a quantum myelin entanglement event."""
        timestamp = time.time()
        
        event_data = {
            "agent_a": agent_a_id,
            "agent_b": agent_b_id,
            "entanglement_strength": entanglement_strength,
            "timestamp": timestamp
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        self.entanglement_events.append(event_data)
        
        # Update statistics
        self.stats["total_entanglements"] += 1
        self.stats["agent_entanglement_count"][agent_a_id] += 1
        self.stats["agent_entanglement_count"][agent_b_id] += 1
        self.stats["entanglement_strength_sum"] += entanglement_strength
        
        if self.stats["total_entanglements"] > 0:
            self.stats["average_entanglement_strength"] = (
                self.stats["entanglement_strength_sum"] / self.stats["total_entanglements"]
            )
        
        # Create log entry
        log_entry = LogEntry(
            timestamp=timestamp,
            level="INFO",
            component="quantum_myelin",
            message=f"Entanglement formed between {agent_a_id} and {agent_b_id} (strength: {entanglement_strength:.3f})",
            data=event_data
        )
        
        self.logs.append(log_entry)
        
        # Print real-time log
        print(f"🔗 Quantum entanglement: {agent_a_id} ↔ {agent_b_id} (strength: {entanglement_strength:.3f})")
    
    def log_meme_infection(
        self,
        agent_id: str,
        meme_id: str,
        infection_strength: float,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log a meme infection event."""
        timestamp = time.time()
        
        event_data = {
            "agent_id": agent_id,
            "meme_id": meme_id,
            "infection_strength": infection_strength,
            "timestamp": timestamp
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        self.meme_infection_events.append(event_data)
        
        # Update statistics
        self.stats["total_infections"] += 1
        self.stats["meme_infection_count"][meme_id] += 1
        
        # Create log entry
        log_entry = LogEntry(
            timestamp=timestamp,
            level="INFO",
            component="meme_infection",
            message=f"Meme {meme_id} infected agent {agent_id} (strength: {infection_strength:.3f})",
            data=event_data
        )
        
        self.logs.append(log_entry)
    
    def log_meme_propagation(
        self,
        source_agent_id: str,
        meme_id: str,
        target_agent_ids: List[str],
        successful_propagations: int,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log a meme propagation event."""
        timestamp = time.time()
        
        event_data = {
            "source_agent": source_agent_id,
            "meme_id": meme_id,
            "target_agents": target_agent_ids,
            "successful_propagations": successful_propagations,
            "timestamp": timestamp
        }
        
        if additional_data:
            event_data.update(additional_data)
        
        self.meme_propagation_events.append(event_data)
        
        # Update statistics
        self.stats["total_propagations"] += successful_propagations
        
        # Create log entry
        log_entry = LogEntry(
            timestamp=timestamp,
            level="INFO",
            component="meme_propagation",
            message=f"Meme {meme_id} propagated from {source_agent_id} to {successful_propagations}/{len(target_agent_ids)} targets",
            data=event_data
        )
        
        self.logs.append(log_entry)
        
        if successful_propagations > 0:
            print(f"🧠 Meme propagation: {meme_id} → {successful_propagations} agents")
    
    def get_summary_statistics(self) -> Dict[str, Any]:
        """Get summary statistics for quantum myelin events."""
        return {
            "total_entanglements": self.stats["total_entanglements"],
            "total_infections": self.stats["total_infections"],
            "total_propagations": self.stats["total_propagations"],
            "average_entanglement_strength": self.stats["average_entanglement_strength"],
            "most_entangled_agents": dict(
                sorted(self.stats["agent_entanglement_count"].items(), 
                      key=lambda x: x[1], reverse=True)[:5]
            ),
            "most_infectious_memes": dict(
                sorted(self.stats["meme_infection_count"].items(),
                      key=lambda x: x[1], reverse=True)[:5]
            ),
            "total_events": len(self.logs)
        }
    
    def get_all_logs(self) -> List[Dict[str, Any]]:
        """Get all logs as dictionaries."""
        return [log.to_dict() for log in self.logs]
    
    def get_entanglement_network(self) -> Dict[str, List[str]]:
        """Get the network of entanglement relationships."""
        network = defaultdict(list)
        
        for event in self.entanglement_events:
            agent_a = event["agent_a"]
            agent_b = event["agent_b"]
            
            network[agent_a].append(agent_b)
            network[agent_b].append(agent_a)
        
        return dict(network)
    
    def export_events_to_file(self, filepath: str):
        """Export all events to a JSON file for analysis."""
        export_data = {
            "entanglement_events": self.entanglement_events,
            "meme_infection_events": self.meme_infection_events,
            "meme_propagation_events": self.meme_propagation_events,
            "statistics": self.stats,
            "export_timestamp": time.time()
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"📁 Quantum myelin events exported to: {filepath}")


class SimulationLogger:
    """General simulation logger for system events and errors."""
    
    def __init__(self):
        """Initialize the simulation logger."""
        self.logs: List[LogEntry] = []
        self.error_count = 0
        self.warning_count = 0
        self.info_count = 0
    
    def log_info(self, message: str, component: str = "simulation", data: Optional[Dict[str, Any]] = None):
        """Log an info-level message."""
        log_entry = LogEntry(
            timestamp=time.time(),
            level="INFO",
            component=component,
            message=message,
            data=data
        )
        
        self.logs.append(log_entry)
        self.info_count += 1
        print(f"ℹ️  {component}: {message}")
    
    def log_warning(self, message: str, component: str = "simulation", data: Optional[Dict[str, Any]] = None):
        """Log a warning-level message."""
        log_entry = LogEntry(
            timestamp=time.time(),
            level="WARNING",
            component=component,
            message=message,
            data=data
        )
        
        self.logs.append(log_entry)
        self.warning_count += 1
        print(f"⚠️  {component}: {message}")
    
    def log_error(self, message: str, component: str = "simulation", data: Optional[Dict[str, Any]] = None):
        """Log an error-level message."""
        log_entry = LogEntry(
            timestamp=time.time(),
            level="ERROR",
            component=component,
            message=message,
            data=data
        )
        
        self.logs.append(log_entry)
        self.error_count += 1
        print(f"❌ {component}: {message}")
    
    def get_all_logs(self) -> List[Dict[str, Any]]:
        """Get all logs as dictionaries."""
        return [log.to_dict() for log in self.logs]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of log statistics."""
        return {
            "total_logs": len(self.logs),
            "info_count": self.info_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "components": list(set(log.component for log in self.logs))
        }
    
    def export_logs_to_file(self, filepath: str):
        """Export logs to a JSON file."""
        export_data = {
            "logs": self.get_all_logs(),
            "summary": self.get_summary(),
            "export_timestamp": time.time()
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"📁 Simulation logs exported to: {filepath}")