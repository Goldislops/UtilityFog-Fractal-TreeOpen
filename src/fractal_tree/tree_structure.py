
"""
TreeStructure implementation for the Fractal Tree MVP.

This module provides the TreeStructure class that manages the overall tree
topology and provides high-level operations for fractal tree management.
"""

import json
import yaml
from typing import Dict, Any, Optional, List, Iterator, Callable, Union
from collections import deque
import networkx as nx
from .tree_node import TreeNode
from .exceptions import TreeNodeError, InvalidNodeError, NodeNotFoundError


class TreeStructure:
    """
    Manages the overall tree topology and provides high-level operations.
    
    The TreeStructure class serves as the main interface for creating,
    manipulating, and analyzing fractal tree structures. It provides
    tree-wide operations, validation, and serialization capabilities.
    """
    
    def __init__(self, root: Optional[TreeNode] = None):
        """
        Initialize a new TreeStructure.
        
        Args:
            root: Root node of the tree. If None, creates empty structure.
        """
        self._root = root
        self._metadata: Dict[str, Any] = {}
        
    @property
    def root(self) -> Optional[TreeNode]:
        """Get the root node of the tree."""
        return self._root
        
    @root.setter
    def root(self, node: Optional[TreeNode]) -> None:
        """Set the root node of the tree."""
        if node is not None and not isinstance(node, TreeNode):
            raise InvalidNodeError("Root must be a TreeNode instance or None")
        self._root = node
        
    @property
    def metadata(self) -> Dict[str, Any]:
        """Get a copy of the tree metadata."""
        return self._metadata.copy()
        
    def set_metadata(self, key: str, value: Any) -> None:
        """Set a metadata value."""
        self._metadata[key] = value
        
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get a metadata value."""
        return self._metadata.get(key, default)
        
    def is_empty(self) -> bool:
        """Check if the tree is empty (no root node)."""
        return self._root is None
        
    def get_node_count(self) -> int:
        """Get the total number of nodes in the tree."""
        if self.is_empty():
            return 0
        return len(list(self._root))
        
    def get_depth(self) -> int:
        """Get the maximum depth of the tree."""
        if self.is_empty():
            return 0
            
        max_depth = 0
        for node in self._root:
            depth = node.get_depth()
            max_depth = max(max_depth, depth)
        return max_depth
        
    def get_leaf_count(self) -> int:
        """Get the number of leaf nodes in the tree."""
        if self.is_empty():
            return 0
        return sum(1 for node in self._root if node.is_leaf())
        
    def get_branch_count(self) -> int:
        """Get the number of branch nodes (non-leaf nodes) in the tree."""
        if self.is_empty():
            return 0
        return sum(1 for node in self._root if not node.is_leaf())
        
    def find_node(self, node_id: str) -> Optional[TreeNode]:
        """
        Find a node by ID in the entire tree.
        
        Args:
            node_id: ID of the node to find.
            
        Returns:
            The found node, or None if not found.
        """
        if self.is_empty():
            return None
        return self._root.find_node(node_id)
        
    def get_node(self, node_id: str) -> TreeNode:
        """
        Get a node by ID, raising exception if not found.
        
        Args:
            node_id: ID of the node to get.
            
        Returns:
            The found node.
            
        Raises:
            NodeNotFoundError: If node is not found.
        """
        node = self.find_node(node_id)
        if node is None:
            raise NodeNotFoundError(f"Node with ID '{node_id}' not found")
        return node
        
    def add_node(self, parent_id: str, child: TreeNode) -> None:
        """
        Add a child node to a parent node in the tree.
        
        Args:
            parent_id: ID of the parent node.
            child: Child node to add.
            
        Raises:
            NodeNotFoundError: If parent node is not found.
        """
        parent = self.get_node(parent_id)
        parent.add_child(child)
        
    def remove_node(self, node_id: str) -> Optional[TreeNode]:
        """
        Remove a node from the tree.
        
        Args:
            node_id: ID of the node to remove.
            
        Returns:
            The removed node, or None if not found.
            
        Note:
            If the root node is removed, the tree becomes empty.
            If a branch node is removed, all its descendants are also removed.
        """
        node = self.find_node(node_id)
        if node is None:
            return None
            
        if node == self._root:
            # Removing root node makes tree empty
            self._root = None
            return node
            
        # Remove from parent
        node.remove_from_parent()
        return node
        
    def traverse_dfs(self, start_node: Optional[TreeNode] = None) -> Iterator[TreeNode]:
        """
        Traverse the tree using depth-first search.
        
        Args:
            start_node: Node to start traversal from. If None, starts from root.
            
        Yields:
            TreeNode: Nodes in DFS order.
        """
        if start_node is None:
            start_node = self._root
            
        if start_node is None:
            return
            
        yield from start_node
        
    def traverse_bfs(self, start_node: Optional[TreeNode] = None) -> Iterator[TreeNode]:
        """
        Traverse the tree using breadth-first search.
        
        Args:
            start_node: Node to start traversal from. If None, starts from root.
            
        Yields:
            TreeNode: Nodes in BFS order.
        """
        if start_node is None:
            start_node = self._root
            
        if start_node is None:
            return
            
        queue = deque([start_node])
        while queue:
            node = queue.popleft()
            yield node
            queue.extend(node.children)
            
    def traverse_level_order(self) -> Iterator[List[TreeNode]]:
        """
        Traverse the tree level by level.
        
        Yields:
            List[TreeNode]: Nodes at each level.
        """
        if self.is_empty():
            return
            
        current_level = [self._root]
        while current_level:
            yield current_level.copy()
            next_level = []
            for node in current_level:
                next_level.extend(node.children)
            current_level = next_level
            
    def filter_nodes(self, predicate: Callable[[TreeNode], bool]) -> List[TreeNode]:
        """
        Filter nodes based on a predicate function.
        
        Args:
            predicate: Function that takes a TreeNode and returns bool.
            
        Returns:
            List of nodes that match the predicate.
        """
        if self.is_empty():
            return []
        return [node for node in self._root if predicate(node)]
        
    def validate_structure(self) -> List[str]:
        """
        Validate the tree structure and return any issues found.
        
        Returns:
            List of validation error messages. Empty list if valid.
        """
        issues = []
        
        if self.is_empty():
            return issues
            
        # Check for orphaned nodes and circular references
        visited = set()
        
        def validate_node(node: TreeNode, path: List[str]) -> None:
            if node.id in path:
                issues.append(f"Circular reference detected: {' -> '.join(path + [node.id])}")
                return
                
            if node.id in visited:
                issues.append(f"Node {node.id} visited multiple times")
                return
                
            visited.add(node.id)
            
            # Check parent-child consistency
            for child in node.children:
                if child.parent != node:
                    issues.append(f"Inconsistent parent-child relationship: {child.id} -> {node.id}")
                validate_node(child, path + [node.id])
                
        # Check root node has no parent
        if self._root.parent is not None:
            issues.append(f"Root node {self._root.id} has a parent")
            
        validate_node(self._root, [])
        
        return issues
        
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about the tree structure.
        
        Returns:
            Dictionary containing various tree statistics.
        """
        if self.is_empty():
            return {
                "node_count": 0,
                "depth": 0,
                "leaf_count": 0,
                "branch_count": 0,
                "average_branching_factor": 0.0,
                "balance_factor": 0.0
            }
            
        node_count = self.get_node_count()
        depth = self.get_depth()
        leaf_count = self.get_leaf_count()
        branch_count = self.get_branch_count()
        
        # Calculate average branching factor
        total_children = sum(node.child_count for node in self._root if not node.is_leaf())
        avg_branching = total_children / branch_count if branch_count > 0 else 0.0
        
        # Calculate balance factor (how balanced the tree is)
        # Perfect balance = 1.0, completely unbalanced = 0.0
        if depth == 0:
            balance_factor = 1.0
        else:
            # Compare actual depth to optimal depth for given node count
            optimal_depth = max(1, int(node_count ** 0.5))  # Simplified metric
            balance_factor = min(1.0, optimal_depth / depth)
            
        return {
            "node_count": node_count,
            "depth": depth,
            "leaf_count": leaf_count,
            "branch_count": branch_count,
            "average_branching_factor": avg_branching,
            "balance_factor": balance_factor
        }
        
    def to_networkx(self) -> nx.DiGraph:
        """
        Convert the tree structure to a NetworkX directed graph.
        
        Returns:
            NetworkX DiGraph representation of the tree.
        """
        graph = nx.DiGraph()
        
        if self.is_empty():
            return graph
            
        # Add nodes with their data
        for node in self._root:
            graph.add_node(node.id, **node.data)
            
        # Add edges
        for node in self._root:
            for child in node.children:
                graph.add_edge(node.id, child.id)
                
        return graph
        
    def from_networkx(self, graph: nx.DiGraph, root_id: str) -> None:
        """
        Create tree structure from a NetworkX directed graph.
        
        Args:
            graph: NetworkX DiGraph to convert.
            root_id: ID of the node to use as root.
            
        Raises:
            InvalidNodeError: If graph is not a valid tree or root_id not found.
        """
        if not nx.is_tree(graph):
            raise InvalidNodeError("Graph is not a valid tree structure")
            
        if root_id not in graph.nodes:
            raise InvalidNodeError(f"Root node '{root_id}' not found in graph")
            
        # Create nodes
        nodes = {}
        for node_id in graph.nodes:
            node_data = graph.nodes[node_id]
            nodes[node_id] = TreeNode(node_id=node_id, data=node_data)
            
        # Build tree structure using BFS from root
        self._root = nodes[root_id]
        queue = deque([root_id])
        visited = {root_id}
        
        while queue:
            parent_id = queue.popleft()
            parent_node = nodes[parent_id]
            
            for child_id in graph.successors(parent_id):
                if child_id not in visited:
                    child_node = nodes[child_id]
                    parent_node.add_child(child_node)
                    queue.append(child_id)
                    visited.add(child_id)
                    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the tree structure to a dictionary.
        
        Returns:
            Dictionary representation of the tree.
        """
        if self.is_empty():
            return {"root": None, "metadata": self._metadata}
            
        def node_to_dict(node: TreeNode) -> Dict[str, Any]:
            return {
                "id": node.id,
                "data": node.data,
                "children": [node_to_dict(child) for child in node.children]
            }
            
        return {
            "root": node_to_dict(self._root),
            "metadata": self._metadata
        }
        
    def from_dict(self, data: Dict[str, Any]) -> None:
        """
        Deserialize tree structure from a dictionary.
        
        Args:
            data: Dictionary representation of the tree.
        """
        self._metadata = data.get("metadata", {})
        
        root_data = data.get("root")
        if root_data is None:
            self._root = None
            return
            
        def dict_to_node(node_data: Dict[str, Any]) -> TreeNode:
            node = TreeNode(node_id=node_data["id"], data=node_data.get("data", {}))
            for child_data in node_data.get("children", []):
                child = dict_to_node(child_data)
                node.add_child(child)
            return node
            
        self._root = dict_to_node(root_data)
        
    def to_json(self, indent: Optional[int] = None) -> str:
        """
        Serialize the tree structure to JSON string.
        
        Args:
            indent: JSON indentation level.
            
        Returns:
            JSON string representation of the tree.
        """
        return json.dumps(self.to_dict(), indent=indent)
        
    def from_json(self, json_str: str) -> None:
        """
        Deserialize tree structure from JSON string.
        
        Args:
            json_str: JSON string representation of the tree.
        """
        data = json.loads(json_str)
        self.from_dict(data)
        
    def to_yaml(self) -> str:
        """
        Serialize the tree structure to YAML string.
        
        Returns:
            YAML string representation of the tree.
        """
        return yaml.dump(self.to_dict(), default_flow_style=False)
        
    def from_yaml(self, yaml_str: str) -> None:
        """
        Deserialize tree structure from YAML string.
        
        Args:
            yaml_str: YAML string representation of the tree.
        """
        data = yaml.safe_load(yaml_str)
        self.from_dict(data)
        
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'TreeStructure':
        """
        Create a tree structure from configuration.
        
        Args:
            config: Configuration dictionary with tree parameters.
            
        Returns:
            New TreeStructure instance.
        """
        tree = cls()
        
        # Set metadata from config
        tree._metadata = config.get("metadata", {})
        
        # Create tree from structure definition
        structure = config.get("structure")
        if structure:
            tree.from_dict({"root": structure, "metadata": tree._metadata})
            
        return tree
        
    def clone(self) -> 'TreeStructure':
        """
        Create a deep copy of the tree structure.
        
        Returns:
            New TreeStructure instance with copied data.
        """
        cloned = TreeStructure()
        cloned.from_dict(self.to_dict())
        return cloned
        
    def __len__(self) -> int:
        """Get the number of nodes in the tree."""
        return self.get_node_count()
        
    def __contains__(self, node_id: str) -> bool:
        """Check if a node with given ID exists in the tree."""
        return self.find_node(node_id) is not None
        
    def __iter__(self) -> Iterator[TreeNode]:
        """Iterate over all nodes in the tree (DFS order)."""
        return self.traverse_dfs()
        
    def __str__(self) -> str:
        """String representation of the tree structure."""
        if self.is_empty():
            return "TreeStructure(empty)"
        stats = self.get_statistics()
        return (f"TreeStructure(nodes={stats['node_count']}, "
                f"depth={stats['depth']}, leaves={stats['leaf_count']})")
        
    def __repr__(self) -> str:
        """Detailed string representation of the tree structure."""
        if self.is_empty():
            return "TreeStructure(root=None, metadata={})"
        return (f"TreeStructure(root={self._root.id}, "
                f"nodes={self.get_node_count()}, metadata={list(self._metadata.keys())})")
