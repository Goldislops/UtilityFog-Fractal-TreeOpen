
"""
Fractal Tree MVP - Core Tree Structure Implementation

This package provides the foundational components for self-organizing,
hierarchical structures within the UtilityFog ecosystem.
"""

__version__ = "0.1.0"
__author__ = "UtilityFog Team"

from .tree_node import TreeNode
from .tree_structure import TreeStructure
from .exceptions import TreeNodeError, CircularReferenceError, InvalidNodeError, NodeNotFoundError

__all__ = [
    "TreeNode",
    "TreeStructure",
    "TreeNodeError", 
    "CircularReferenceError",
    "InvalidNodeError",
    "NodeNotFoundError"
]
