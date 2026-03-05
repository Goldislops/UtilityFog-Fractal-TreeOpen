
"""
TreeNode implementation for the Fractal Tree MVP.

This module provides the fundamental TreeNode class that serves as the building
block for all fractal tree structures.
"""

import uuid
import weakref
from typing import Dict, Any, Optional, Set, List, Iterator
from .exceptions import CircularReferenceError, InvalidNodeError


class TreeNode:
    """
    A node in a fractal tree structure.
    
    Each node maintains parent-child relationships and can store arbitrary data.
    Uses weak references to prevent memory leaks and implements safeguards
    against circular references.
    """
    
    def __init__(self, node_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        """
        Initialize a new TreeNode.
        
        Args:
            node_id: Unique identifier for the node. If None, generates UUID4.
            data: Initial data to store in the node.
            
        Raises:
            InvalidNodeError: If node_id is invalid format.
        """
        if node_id is None:
            self._id = str(uuid.uuid4())
        else:
            self._validate_node_id(node_id)
            self._id = node_id
        
        self._data: Dict[str, Any] = data.copy() if data else {}
        self._parent_ref: Optional[weakref.ReferenceType] = None
        self._children: Dict[str, 'TreeNode'] = {}
        
    def _validate_node_id(self, node_id: str) -> None:
        """Validate that node_id is a valid format."""
        if not isinstance(node_id, str) or not node_id or not node_id.strip():
            raise InvalidNodeError("Node ID must be a non-empty string")
            
    @property
    def id(self) -> str:
        """Get the unique identifier for this node."""
        return self._id
        
    @property
    def data(self) -> Dict[str, Any]:
        """Get a copy of the node's data."""
        return self._data.copy()
        
    def set_data(self, key: str, value: Any) -> None:
        """Set a data value for the given key."""
        self._data[key] = value
        
    def get_data(self, key: str, default: Any = None) -> Any:
        """Get a data value for the given key."""
        return self._data.get(key, default)
        
    def remove_data(self, key: str) -> Any:
        """Remove and return a data value for the given key."""
        return self._data.pop(key, None)
        
    @property
    def parent(self) -> Optional['TreeNode']:
        """Get the parent node, or None if this is a root node."""
        if self._parent_ref is None:
            return None
        parent = self._parent_ref()
        if parent is None:
            # Parent was garbage collected, clean up the reference
            self._parent_ref = None
        return parent
        
    @property
    def children(self) -> List['TreeNode']:
        """Get a list of all child nodes."""
        return list(self._children.values())
        
    @property
    def child_count(self) -> int:
        """Get the number of child nodes."""
        return len(self._children)
        
    def get_child(self, node_id: str) -> Optional['TreeNode']:
        """Get a child node by ID."""
        return self._children.get(node_id)
        
    def has_child(self, node_id: str) -> bool:
        """Check if a child node exists with the given ID."""
        return node_id in self._children
        
    def add_child(self, child: 'TreeNode') -> None:
        """
        Add a child node.
        
        Args:
            child: The node to add as a child.
            
        Raises:
            InvalidNodeError: If child is None or already has a parent.
            CircularReferenceError: If adding child would create a cycle.
        """
        if child is None:
            raise InvalidNodeError("Cannot add None as a child")
            
        if child.parent is not None:
            raise InvalidNodeError(f"Node {child.id} already has a parent")
            
        if child.id == self.id:
            raise CircularReferenceError("Cannot add node as child of itself")
            
        # Check for circular reference by traversing up the tree
        if self._would_create_cycle(child):
            raise CircularReferenceError(
                f"Adding node {child.id} as child would create a circular reference"
            )
            
        # Add the child
        self._children[child.id] = child
        child._parent_ref = weakref.ref(self)
        
    def remove_child(self, node_id: str) -> Optional['TreeNode']:
        """
        Remove a child node by ID.
        
        Args:
            node_id: ID of the child to remove.
            
        Returns:
            The removed child node, or None if not found.
        """
        child = self._children.pop(node_id, None)
        if child:
            child._parent_ref = None
        return child
        
    def remove_from_parent(self) -> None:
        """Remove this node from its parent."""
        parent = self.parent
        if parent:
            parent.remove_child(self.id)
            
    def _would_create_cycle(self, potential_child: 'TreeNode') -> bool:
        """Check if adding potential_child would create a cycle."""
        # Check if potential_child is an ancestor of self
        # If so, adding it as a child would create a cycle
        current = self
        visited: Set[str] = set()
        
        while current is not None:
            if current.id in visited:
                # Found a cycle in our ancestry, break to avoid infinite loop
                break
            visited.add(current.id)
            
            if current.id == potential_child.id:
                return True
                
            current = current.parent
            
        return False
        
    def is_root(self) -> bool:
        """Check if this node is a root node (has no parent)."""
        return self.parent is None
        
    def is_leaf(self) -> bool:
        """Check if this node is a leaf node (has no children)."""
        return len(self._children) == 0
        
    def get_depth(self) -> int:
        """Get the depth of this node (distance from root)."""
        depth = 0
        current = self.parent
        while current is not None:
            depth += 1
            current = current.parent
        return depth
        
    def get_ancestors(self) -> List['TreeNode']:
        """Get all ancestor nodes from parent to root."""
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        return ancestors
        
    def get_descendants(self) -> List['TreeNode']:
        """Get all descendant nodes using depth-first traversal."""
        descendants = []
        for child in self.children:
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants
        
    def find_node(self, node_id: str) -> Optional['TreeNode']:
        """Find a node by ID in this subtree."""
        if self.id == node_id:
            return self
            
        for child in self.children:
            found = child.find_node(node_id)
            if found:
                return found
                
        return None
        
    def __iter__(self) -> Iterator['TreeNode']:
        """Iterate over all nodes in this subtree (depth-first)."""
        yield self
        for child in self.children:
            yield from child
            
    def __str__(self) -> str:
        """String representation of the node."""
        return f"TreeNode(id={self.id}, children={self.child_count})"
        
    def __repr__(self) -> str:
        """Detailed string representation of the node."""
        parent_id = self.parent.id if self.parent else None
        return (f"TreeNode(id={self.id}, parent={parent_id}, "
                f"children={self.child_count}, data_keys={list(self._data.keys())})")
