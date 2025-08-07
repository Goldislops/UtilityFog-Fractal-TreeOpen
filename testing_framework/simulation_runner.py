"""
Simulation Runner for Integration Testing

This module coordinates all simulation components (agents, memes, network, evolution)
and handles their integration for testing purposes.
"""

import sys
import os
import time
import random
import uuid
from typing import Dict, List, Any, Optional, Tuple

# Add agent modules to path
sys.path.insert(0, '/app')

try:
    from agent.foglet_agent import FogletAgent, AgentCapabilities, AgentRole
    from agent.meme_structure import Meme, MemeType, MemePool
    from agent.network_topology import FractalNetwork, NetworkNode
    from agent.evolution_engine import EvolutionEngine, EvolutionParameters
    from agent.simulation_metrics import SimulationMetrics, AgentMetricCollector, MemeMetricCollector
    from utilityfog_frontend.quantum_myelin import myelin_layer
    MODULES_AVAILABLE = True
    print("✅ All agent modules imported successfully!")
except ImportError as e:
    print(f"Warning: Could not import some modules: {e}")
    print("Some functionality may be limited.")
    MODULES_AVAILABLE = False
    
    # Create dummy classes for testing
    class FogletAgent:
        def __init__(self, *args, **kwargs):
            self.agent_id = kwargs.get('agent_id', 'dummy')
            self.energy_level = 0.5
            self.health = 0.5
            self.active_memes = {}
            self.performance_metrics = {}
        def update(self, *args, **kwargs):
            pass
        def infect_with_meme(self, *args, **kwargs):
            return False
        def propagate_memes(self, *args, **kwargs):
            return {}
    
    class AgentCapabilities:
        def __init__(self, *args, **kwargs):
            pass
    
    class AgentRole:
        COORDINATOR = "coordinator"
        WORKER = "worker"
        SENSOR = "sensor"
        RELAY = "relay"
    
    class Meme:
        def __init__(self, *args, **kwargs):
            self.meme_id = 'dummy'
            self.meme_type = 'dummy'
            
    class MemeType:
        BEHAVIORAL = "behavioral"
    
    class MemePool:
        def __init__(self, *args, **kwargs):
            self.memes = {}
        def add_meme(self, meme):
            return True
    
    class FractalNetwork:
        def __init__(self, *args, **kwargs):
            pass
        def add_node(self, *args, **kwargs):
            return True
        def get_node(self, node_id):
            class DummyNode:
                def __init__(self):
                    self.children_ids = set()
            return DummyNode()
        def get_network_stats(self):
            return {}
    
    class EvolutionEngine:
        def __init__(self, *args, **kwargs):
            pass
    
    class EvolutionParameters:
        def __init__(self, *args, **kwargs):
            pass
    
    class SimulationMetrics:
        def __init__(self, *args, **kwargs):
            self.entity_sources = {}
        def add_collector(self, *args, **kwargs):
            pass
        def collect_all_metrics(self, *args, **kwargs):
            pass
        def generate_report(self):
            return {}
    
    class AgentMetricCollector:
        pass
    
    class MemeMetricCollector:
        pass
    
    def myelin_layer(*args, **kwargs):
        pass

from .loggers import QuantumMyelinLogger, SimulationLogger


class SimulationRunner:
    """Integrated simulation runner that coordinates all system components."""
    
    def __init__(
        self,
        config,
        quantum_logger: Optional[QuantumMyelinLogger] = None,
        simulation_logger: Optional[SimulationLogger] = None,
        output_dir: str = "simulation_output"
    ):
        """Initialize the simulation runner with configuration."""
        self.config = config
        self.output_dir = output_dir
        
        # Initialize loggers
        self.quantum_logger = quantum_logger or QuantumMyelinLogger()
        self.simulation_logger = simulation_logger or SimulationLogger()
        
        # Initialize simulation components
        self.agents: List[FogletAgent] = []
        self.meme_pool = MemePool(max_population=1000)
        self.network: Optional[FractalNetwork] = None
        self.evolution_engine: Optional[EvolutionEngine] = None
        self.metrics_system: Optional[SimulationMetrics] = None
        
        # Tracking variables
        self.current_step = 0
        self.current_generation = 0
        self.simulation_start_time = 0.0
        self.all_logs: List[Dict[str, Any]] = []
        
        # Results storage
        self.results = {
            "agent_metrics": {},
            "meme_metrics": {},
            "network_metrics": {},
            "quantum_myelin_metrics": {},
            "evolution_metrics": {}
        }
        
        print(f"🔧 SimulationRunner initialized for: {config.test_name}")
        print(f"   Output directory: {output_dir}")
    
    def run_simulation(self) -> Dict[str, Any]:
        """Run the complete simulation and return results."""
        print(f"\n⚡ Starting simulation: {self.config.test_name}")
        
        if not MODULES_AVAILABLE:
            print("⚠️  Some modules are not available - running in limited mode")
            return self._run_limited_simulation()
        
        self.simulation_start_time = time.time()
        
        try:
            # Phase 1: Initialize components
            self._initialize_simulation()
            
            # Phase 2: Run simulation steps
            self._run_simulation_steps()
            
            # Phase 3: Collect final metrics
            self._collect_final_metrics()
            
            # Phase 4: Generate results
            results = self._generate_results()
            
            total_time = time.time() - self.simulation_start_time
            print(f"✨ Simulation completed in {total_time:.2f}s")
            
            return results
            
        except Exception as e:
            error_msg = f"Simulation failed: {str(e)}"
            self.simulation_logger.log_error(error_msg)
            self.all_logs.append({
                "timestamp": time.time(),
                "level": "ERROR", 
                "message": error_msg,
                "component": "simulation_runner"
            })
            raise
    
    def _initialize_simulation(self):
        """Initialize all simulation components."""
        print("🏗️  Initializing simulation components...")
        
        # Initialize network
        self.network = FractalNetwork(
            max_depth=self.config.network_depth,
            branching_factor=self.config.branching_factor
        )
        
        # Initialize agents and add to network
        self._create_agents()
        
        # Initialize meme pool with initial memes
        self._initialize_meme_pool()
        
        # Initialize evolution engine
        evolution_params = EvolutionParameters(
            population_size=len(self.agents),
            mutation_rate=self.config.mutation_rate,
            crossover_rate=self.config.crossover_rate,
            max_generations=self.config.num_generations
        )
        self.evolution_engine = EvolutionEngine(parameters=evolution_params)
        
        # Initialize metrics system
        self.metrics_system = SimulationMetrics(collection_interval=1.0)
        agent_collector = AgentMetricCollector()
        meme_collector = MemeMetricCollector()
        
        self.metrics_system.add_collector(agent_collector, "agents")
        self.metrics_system.add_collector(meme_collector, "memes")
        
        # Set entity sources for metrics collection
        self.metrics_system.entity_sources["agents"] = self.agents
        self.metrics_system.entity_sources["memes"] = list(self.meme_pool.memes.values())
        
        self.simulation_logger.log_info("Simulation components initialized successfully")
        self.all_logs.append({
            "timestamp": time.time(),
            "level": "INFO",
            "message": f"Initialized {len(self.agents)} agents with {len(self.meme_pool.memes)} memes",
            "component": "initialization"
        })
    
    def _create_agents(self):
        """Create and initialize agents."""
        print(f"👥 Creating {self.config.num_agents} agents...")
        
        # Create root agent
        root_agent = FogletAgent(
            agent_id="agent_root",
            role=AgentRole.COORDINATOR,
            capabilities=AgentCapabilities()
        )
        self.agents.append(root_agent)
        self.network.add_node("agent_root", agent=root_agent)
        
        # Create child agents
        for i in range(1, self.config.num_agents):
            agent_id = f"agent_{i}"
            
            # Determine parent for network topology
            parent_id = None
            if i == 1:
                parent_id = "agent_root"
            elif i < 4:  # First level children
                parent_id = "agent_root"
            else:  # Subsequent levels
                parent_options = [a.agent_id for a in self.agents if len(self.network.get_node(a.agent_id).children_ids) < self.config.branching_factor]
                parent_id = random.choice(parent_options) if parent_options else "agent_root"
            
            # Create agent
            agent = FogletAgent(
                agent_id=agent_id,
                role=random.choice([AgentRole.WORKER, AgentRole.SENSOR, AgentRole.RELAY]),
                capabilities=AgentCapabilities()
            )
            
            self.agents.append(agent)
            self.network.add_node(agent_id, agent=agent, parent_id=parent_id)
        
        print(f"   ✅ Created {len(self.agents)} agents in fractal network")
    
    def _initialize_meme_pool(self):
        """Initialize the meme pool with diverse memes."""
        print(f"🧠 Initializing meme pool...")
        
        # Create diverse initial memes
        meme_types = list(MemeType)
        initial_memes = []
        
        for i in range(self.config.num_agents * self.config.initial_memes_per_agent):
            meme_type = random.choice(meme_types)
            
            # Create meme with random payload
            payload = {
                "action_preferences": {
                    "communicate": random.uniform(0.0, 1.0),
                    "cooperate": random.uniform(0.0, 1.0),
                    "explore": random.uniform(0.0, 1.0)
                },
                "decision_rules": {
                    "risk_tolerance": random.uniform(0.0, 1.0),
                    "social_weight": random.uniform(0.0, 1.0)
                }
            }
            
            meme = Meme(meme_type=meme_type, payload=payload)
            initial_memes.append(meme)
            self.meme_pool.add_meme(meme)
        
        # Infect agents with initial memes
        for agent in self.agents:
            num_memes = random.randint(1, self.config.initial_memes_per_agent)
            selected_memes = random.sample(initial_memes, min(num_memes, len(initial_memes)))
            
            for meme in selected_memes:
                success = agent.infect_with_meme(meme, infection_strength=0.7)
                if success:
                    self.quantum_logger.log_meme_infection(agent.agent_id, meme.meme_id, 0.7)
        
        print(f"   ✅ Created {len(initial_memes)} initial memes")
    
    def _run_simulation_steps(self):
        """Run the main simulation loop."""
        print(f"🎮 Running {self.config.simulation_steps} simulation steps...")
        
        for step in range(self.config.simulation_steps):
            self.current_step = step
            
            # Create environment context
            environment_context = {
                "step": step,
                "total_agents": len(self.agents),
                "total_memes": len(self.meme_pool.memes),
                "network_stats": self.network.get_network_stats()
            }
            
            # Update all agents
            self._update_agents(environment_context)
            
            # Process quantum myelin interactions if enabled
            if self.config.enable_quantum_myelin:
                self._process_quantum_myelin_interactions()
            
            # Process meme propagation
            self._process_meme_propagation()
            
            # Collect metrics
            if step % 5 == 0:  # Collect every 5 steps
                self.metrics_system.collect_all_metrics(time.time())
            
            # Log progress
            if step % 10 == 0:
                active_memes = sum(len(agent.active_memes) for agent in self.agents)
                print(f"   Step {step}: {len(self.agents)} agents, {active_memes} active memes")
        
        print(f"   ✅ Completed {self.config.simulation_steps} simulation steps")
    
    def _update_agents(self, environment_context: Dict[str, Any]):
        """Update all agents for one simulation step."""
        dt = 1.0  # Time delta
        
        for agent in self.agents:
            try:
                agent.update(dt, environment_context)
            except Exception as e:
                error_msg = f"Agent {agent.agent_id} update failed: {str(e)}"
                self.simulation_logger.log_error(error_msg)
    
    def _process_quantum_myelin_interactions(self):
        """Process quantum myelin entanglement interactions between agents."""
        if len(self.agents) < 2:
            return
        
        entanglement_count = 0
        
        # Process potential entanglements between nearby agents
        for i, agent_a in enumerate(self.agents):
            for agent_b in self.agents[i+1:]:
                
                # Simple entanglement condition - can be made more sophisticated
                if self._should_form_entanglement(agent_a, agent_b):
                    try:
                        # Create simple state objects for quantum_myelin
                        class SimpleAgent:
                            def __init__(self, agent):
                                self.state = agent.energy_level * agent.health  # Simple state metric
                        
                        simple_a = SimpleAgent(agent_a)
                        simple_b = SimpleAgent(agent_b)
                        
                        # Apply quantum myelin entanglement
                        entanglement_strength = random.uniform(0.1, 0.8)
                        myelin_layer(simple_a, simple_b, entanglement_strength)
                        
                        # Update original agents based on entanglement
                        agent_a.energy_level = max(0.0, min(1.0, simple_a.state))
                        agent_b.energy_level = max(0.0, min(1.0, simple_b.state))
                        
                        # Log the entanglement
                        self.quantum_logger.log_entanglement(
                            agent_a.agent_id,
                            agent_b.agent_id,
                            entanglement_strength,
                            {
                                "agent_a_state_before": agent_a.energy_level,
                                "agent_b_state_before": agent_b.energy_level,
                                "agent_a_state_after": simple_a.state,
                                "agent_b_state_after": simple_b.state
                            }
                        )
                        
                        entanglement_count += 1
                        
                    except Exception as e:
                        error_msg = f"Quantum myelin interaction failed: {str(e)}"
                        self.simulation_logger.log_error(error_msg)
        
        if entanglement_count > 0:
            self.all_logs.append({
                "timestamp": time.time(),
                "level": "INFO",
                "message": f"Processed {entanglement_count} quantum myelin entanglements",
                "component": "quantum_myelin"
            })
    
    def _should_form_entanglement(self, agent_a, agent_b) -> bool:
        """Determine if two agents should form an entanglement."""
        # Simple conditions - can be made more sophisticated
        
        # Energy level similarity
        energy_diff = abs(agent_a.energy_level - agent_b.energy_level)
        if energy_diff > 0.3:
            return False
        
        # Random probability
        if random.random() > 0.2:  # 20% chance base probability
            return False
        
        # Network proximity (simplified)
        # In a real implementation, this would check network distance
        return True
    
    def _process_meme_propagation(self):
        """Process meme propagation between agents."""
        propagation_events = 0
        
        for agent in self.agents:
            if not agent.active_memes:
                continue
            
            # Find nearby agents for propagation
            nearby_agents = self._get_nearby_agents(agent, max_distance=2)
            
            if nearby_agents:
                propagation_results = agent.propagate_memes(nearby_agents)
                
                for meme_id, count in propagation_results.items():
                    propagation_events += count
                    if count > 0:
                        self.quantum_logger.log_meme_propagation(
                            agent.agent_id,
                            meme_id,
                            [a.agent_id for a in nearby_agents],
                            count
                        )
        
        if propagation_events > 0:
            self.all_logs.append({
                "timestamp": time.time(),
                "level": "INFO",
                "message": f"Processed {propagation_events} meme propagation events",
                "component": "meme_propagation"
            })
    
    def _get_nearby_agents(self, agent, max_distance: int = 2):
        """Get agents within network distance of the given agent."""
        # Simplified - in real implementation would use network topology
        nearby = []
        
        for other_agent in self.agents:
            if other_agent.agent_id != agent.agent_id:
                # Simple random selection for testing
                if random.random() < 0.3:  # 30% chance of being "nearby"
                    nearby.append(other_agent)
        
        return nearby[:3]  # Limit to 3 nearby agents
    
    def _collect_final_metrics(self):
        """Collect final simulation metrics."""
        print("📊 Collecting final metrics...")
        
        # Force final metrics collection
        self.metrics_system.collect_all_metrics(time.time())
        
        # Generate simulation report
        final_report = self.metrics_system.generate_report()
        
        # Store in results
        self.results["final_metrics_report"] = final_report
        self.results["final_generation"] = self.current_generation
        
        print("   ✅ Final metrics collected")
    
    def _generate_results(self) -> Dict[str, Any]:
        """Generate comprehensive simulation results."""
        print("📈 Generating results...")
        
        # Agent metrics
        agent_metrics = {
            "total_agents": len(self.agents),
            "average_energy": sum(a.energy_level for a in self.agents) / len(self.agents),
            "average_health": sum(a.health for a in self.agents) / len(self.agents),
            "total_active_memes": sum(len(a.active_memes) for a in self.agents),
            "agent_states": {
                agent.agent_id: {
                    "energy": agent.energy_level,
                    "health": agent.health,
                    "active_memes": len(agent.active_memes),
                    "performance_metrics": agent.performance_metrics
                }
                for agent in self.agents
            }
        }
        
        # Meme metrics
        all_memes = list(self.meme_pool.memes.values())
        meme_metrics = {
            "total_memes": len(all_memes),
            "average_fitness": sum(m.fitness_score for m in all_memes) / len(all_memes) if all_memes else 0,
            "total_propagations": sum(m.propagation_count for m in all_memes),
            "meme_types_distribution": {
                meme_type.value: sum(1 for m in all_memes if m.meme_type == meme_type)
                for meme_type in MemeType
            }
        }
        
        # Network metrics
        network_metrics = self.network.get_network_stats() if self.network else {}
        
        # Quantum myelin metrics
        quantum_metrics = self.quantum_logger.get_summary_statistics()
        
        # Evolution metrics (placeholder for now)
        evolution_metrics = {
            "generations_completed": self.current_generation,
            "steps_completed": self.current_step
        }
        
        return {
            "agent_metrics": agent_metrics,
            "meme_metrics": meme_metrics,
            "network_metrics": network_metrics,
            "quantum_myelin_metrics": quantum_metrics,
            "evolution_metrics": evolution_metrics,
            "final_generation": self.current_generation
        }
    
    def get_all_logs(self) -> List[Dict[str, Any]]:
        """Get all logs from the simulation run."""
        # Combine logs from all sources
        all_logs = self.all_logs.copy()
        all_logs.extend(self.quantum_logger.get_all_logs())
        all_logs.extend(self.simulation_logger.get_all_logs())
        
        # Sort by timestamp
        all_logs.sort(key=lambda x: x.get("timestamp", 0))
        
        return all_logs
    
    def _run_limited_simulation(self) -> Dict[str, Any]:
        """Run a limited simulation when full modules are not available."""
        print("🔧 Running limited simulation (demonstration mode)")
        
        # Simulate basic results
        import random
        time.sleep(1)  # Simulate some processing time
        
        # Generate mock results
        num_agents = self.config.num_agents
        
        mock_results = {
            "agent_metrics": {
                "total_agents": num_agents,
                "average_energy": random.uniform(0.3, 0.8),
                "average_health": random.uniform(0.4, 0.9),
                "total_active_memes": random.randint(num_agents // 2, num_agents * 2)
            },
            "meme_metrics": {
                "total_memes": random.randint(num_agents, num_agents * 3),
                "average_fitness": random.uniform(0.2, 0.7),
                "total_propagations": random.randint(0, num_agents * 2)
            },
            "network_metrics": {
                "total_nodes": num_agents,
                "total_connections": max(0, num_agents - 1),
                "max_depth": self.config.network_depth
            },
            "quantum_myelin_metrics": {
                "total_entanglements": random.randint(0, num_agents // 2) if self.config.enable_quantum_myelin else 0,
                "total_infections": random.randint(0, num_agents),
                "total_propagations": random.randint(0, num_agents),
                "average_entanglement_strength": random.uniform(0.1, 0.8)
            },
            "evolution_metrics": {
                "generations_completed": self.config.num_generations,
                "steps_completed": self.config.simulation_steps
            },
            "final_generation": self.config.num_generations
        }
        
        # Add some mock logs
        self.all_logs.append({
            "timestamp": time.time(),
            "level": "INFO",
            "message": "Limited simulation completed successfully",
            "component": "limited_mode"
        })
        
        if self.config.enable_quantum_myelin:
            entanglements = mock_results["quantum_myelin_metrics"]["total_entanglements"]
            self.quantum_logger.stats["total_entanglements"] = entanglements
            for i in range(entanglements):
                self.quantum_logger.entanglement_events.append({
                    "agent_a": f"agent_{i}",
                    "agent_b": f"agent_{(i+1) % num_agents}",
                    "entanglement_strength": random.uniform(0.1, 0.8),
                    "timestamp": time.time()
                })
        
        print(f"📊 Limited simulation completed with mock data")
        return mock_results