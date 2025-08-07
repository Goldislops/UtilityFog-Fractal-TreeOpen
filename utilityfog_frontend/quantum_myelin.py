def myelin_layer(agent_a, agent_b, entanglement_strength=1.0):
    """
    Symbolic abstraction of entangled communication between agents.

    - agent_a / agent_b: objects with internal state
    - entanglement_strength: float (0 to 1), governs influence transfer
    """
    delta_state = agent_b.state - agent_a.state
    agent_a.state += entanglement_strength * delta_state
    agent_b.state -= entanglement_strength * delta_state
