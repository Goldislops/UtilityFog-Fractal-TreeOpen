
"""
Fractal Tree MVP - Core Tree Structure Implementation

This package provides the foundational components for self-organizing,
hierarchical structures within the UtilityFog ecosystem.
"""

__version__ = "0.1.0"
__author__ = "UtilityFog Team"

from .tree_node import TreeNode
from .exceptions import TreeNodeError, CircularReferenceError, InvalidNodeError

__all__ = [
    "TreeNode",
    "TreeNodeError", 
    "CircularReferenceError",
    "InvalidNodeError"
]
