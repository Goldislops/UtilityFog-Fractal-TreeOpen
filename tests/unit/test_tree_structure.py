
"""
Unit tests for TreeStructure class.

Tests cover tree management, traversal, validation, serialization,
and performance with large trees.
"""

import pytest
import json
import yaml
import networkx as nx
from src.fractal_tree import TreeNode, TreeStructure, InvalidNodeError, NodeNotFoundError


class TestTreeStructureCreation:
    """Test TreeStructure creation and basic properties."""
    
    def test_create_empty_tree(self):
        """Test creating an empty tree structure."""
        tree = TreeStructure()
        assert tree.is_empty()
        assert tree.root is None
        assert tree.get_node_count() == 0
        assert tree.get_depth() == 0
        
    def test_create_tree_with_root(self):
        """Test creating a tree with a root node."""
        root = TreeNode(node_id="root")
        tree = TreeStructure(root)
        assert not tree.is_empty()
        assert tree.root == root
        assert tree.get_node_count() == 1
        assert tree.get_depth() == 0
        
    def test_set_root_node(self):
        """Test setting the root node."""
        tree = TreeStructure()
        root = TreeNode(node_id="root")
        tree.root = root
        assert tree.root == root
        assert not tree.is_empty()
        
    def test_set_invalid_root_raises_error(self):
        """Test that setting invalid root raises error."""
        tree = TreeStructure()
        with pytest.raises(InvalidNodeError):
            tree.root = "not a node"


class TestTreeStructureMetadata:
    """Test metadata management functionality."""
    
    def test_set_and_get_metadata(self):
        """Test setting and getting metadata."""
        tree = TreeStructure()
        tree.set_metadata("key1", "value1")
        tree.set_metadata("key2", 42)
        
        assert tree.get_metadata("key1") == "value1"
        assert tree.get_metadata("key2") == 42
        
    def test_get_nonexistent_metadata_returns_default(self):
        """Test getting non-existent metadata returns default."""
        tree = TreeStructure()
        assert tree.get_metadata("nonexistent") is None
        assert tree.get_metadata("nonexistent", "default") == "default"
        
    def test_metadata_property_returns_copy(self):
        """Test that metadata property returns a copy."""
        tree = TreeStructure()
        tree.set_metadata("key", "value")
        metadata_copy = tree.metadata
        metadata_copy["key"] = "modified"
        assert tree.get_metadata("key") == "value"


class TestTreeStructureNodeManagement:
    """Test node management operations."""
    
    def test_find_node_in_tree(self):
        """Test finding nodes in the tree."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        tree = TreeStructure(root)
        
        assert tree.find_node("root") == root
        assert tree.find_node("child1") == child1
        assert tree.find_node("grandchild") == grandchild
        assert tree.find_node("nonexistent") is None
        
    def test_get_node_raises_error_if_not_found(self):
        """Test that get_node raises error if node not found."""
        tree = TreeStructure(TreeNode(node_id="root"))
        
        with pytest.raises(NodeNotFoundError):
            tree.get_node("nonexistent")
            
    def test_add_node_to_tree(self):
        """Test adding nodes to the tree."""
        root = TreeNode(node_id="root")
        tree = TreeStructure(root)
        
        new_child = TreeNode(node_id="new_child")
        tree.add_node("root", new_child)
        
        assert tree.find_node("new_child") == new_child
        assert new_child.parent == root
        
    def test_add_node_to_nonexistent_parent_raises_error(self):
        """Test that adding node to non-existent parent raises error."""
        tree = TreeStructure(TreeNode(node_id="root"))
        new_child = TreeNode(node_id="new_child")
        
        with pytest.raises(NodeNotFoundError):
            tree.add_node("nonexistent", new_child)
            
    def test_remove_node_from_tree(self):
        """Test removing nodes from the tree."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        root.add_child(child)
        
        tree = TreeStructure(root)
        removed = tree.remove_node("child")
        
        assert removed == child
        assert tree.find_node("child") is None
        assert child.parent is None
        
    def test_remove_root_node_makes_tree_empty(self):
        """Test that removing root node makes tree empty."""
        root = TreeNode(node_id="root")
        tree = TreeStructure(root)
        
        removed = tree.remove_node("root")
        
        assert removed == root
        assert tree.is_empty()
        
    def test_remove_nonexistent_node_returns_none(self):
        """Test that removing non-existent node returns None."""
        tree = TreeStructure(TreeNode(node_id="root"))
        assert tree.remove_node("nonexistent") is None


class TestTreeStructureStatistics:
    """Test tree statistics and analysis."""
    
    def test_get_node_count(self):
        """Test getting node count."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        tree = TreeStructure(root)
        assert tree.get_node_count() == 4
        
    def test_get_depth(self):
        """Test getting tree depth."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child)
        child.add_child(grandchild)
        
        tree = TreeStructure(root)
        assert tree.get_depth() == 2
        
    def test_get_leaf_count(self):
        """Test getting leaf node count."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        tree = TreeStructure(root)
        assert tree.get_leaf_count() == 2  # child2 and grandchild
        
    def test_get_branch_count(self):
        """Test getting branch node count."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        tree = TreeStructure(root)
        assert tree.get_branch_count() == 2  # root and child1
        
    def test_get_statistics(self):
        """Test getting comprehensive statistics."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        
        root.add_child(child1)
        root.add_child(child2)
        
        tree = TreeStructure(root)
        stats = tree.get_statistics()
        
        assert stats["node_count"] == 3
        assert stats["depth"] == 1
        assert stats["leaf_count"] == 2
        assert stats["branch_count"] == 1
        assert stats["average_branching_factor"] == 2.0
        assert 0.0 <= stats["balance_factor"] <= 1.0


class TestTreeStructureTraversal:
    """Test tree traversal algorithms."""
    
    def test_traverse_dfs(self):
        """Test depth-first traversal."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        tree = TreeStructure(root)
        nodes = list(tree.traverse_dfs())
        
        assert len(nodes) == 4
        assert nodes[0] == root
        # DFS should visit child1 and its descendants before child2
        child1_index = nodes.index(child1)
        grandchild_index = nodes.index(grandchild)
        child2_index = nodes.index(child2)
        assert child1_index < grandchild_index < child2_index
        
    def test_traverse_bfs(self):
        """Test breadth-first traversal."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        tree = TreeStructure(root)
        nodes = list(tree.traverse_bfs())
        
        assert len(nodes) == 4
        assert nodes[0] == root
        # BFS should visit all children before grandchildren
        assert child1 in nodes[1:3]
        assert child2 in nodes[1:3]
        assert nodes[3] == grandchild
        
    def test_traverse_level_order(self):
        """Test level-order traversal."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        tree = TreeStructure(root)
        levels = list(tree.traverse_level_order())
        
        assert len(levels) == 3
        assert levels[0] == [root]
        assert set(levels[1]) == {child1, child2}
        assert levels[2] == [grandchild]
        
    def test_filter_nodes(self):
        """Test filtering nodes by predicate."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        
        root.add_child(child1)
        root.add_child(child2)
        
        tree = TreeStructure(root)
        
        # Filter leaf nodes
        leaves = tree.filter_nodes(lambda node: node.is_leaf())
        assert len(leaves) == 2
        assert child1 in leaves
        assert child2 in leaves
        
        # Filter by ID pattern
        child_nodes = tree.filter_nodes(lambda node: "child" in node.id)
        assert len(child_nodes) == 2


class TestTreeStructureValidation:
    """Test tree structure validation."""
    
    def test_validate_valid_structure(self):
        """Test validation of valid tree structure."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        root.add_child(child)
        
        tree = TreeStructure(root)
        issues = tree.validate_structure()
        assert len(issues) == 0
        
    def test_validate_empty_tree(self):
        """Test validation of empty tree."""
        tree = TreeStructure()
        issues = tree.validate_structure()
        assert len(issues) == 0


class TestTreeStructureSerialization:
    """Test serialization and deserialization."""
    
    def test_to_dict_and_from_dict(self):
        """Test dictionary serialization."""
        root = TreeNode(node_id="root", data={"key": "value"})
        child = TreeNode(node_id="child", data={"num": 42})
        root.add_child(child)
        
        tree = TreeStructure(root)
        tree.set_metadata("version", "1.0")
        
        # Serialize to dict
        data = tree.to_dict()
        assert data["root"]["id"] == "root"
        assert data["root"]["data"]["key"] == "value"
        assert len(data["root"]["children"]) == 1
        assert data["metadata"]["version"] == "1.0"
        
        # Deserialize from dict
        new_tree = TreeStructure()
        new_tree.from_dict(data)
        
        assert new_tree.root.id == "root"
        assert new_tree.root.get_data("key") == "value"
        assert new_tree.get_metadata("version") == "1.0"
        assert len(new_tree.root.children) == 1
        
    def test_to_json_and_from_json(self):
        """Test JSON serialization."""
        root = TreeNode(node_id="root")
        tree = TreeStructure(root)
        
        json_str = tree.to_json()
        assert isinstance(json_str, str)
        
        new_tree = TreeStructure()
        new_tree.from_json(json_str)
        assert new_tree.root.id == "root"
        
    def test_to_yaml_and_from_yaml(self):
        """Test YAML serialization."""
        root = TreeNode(node_id="root")
        tree = TreeStructure(root)
        
        yaml_str = tree.to_yaml()
        assert isinstance(yaml_str, str)
        
        new_tree = TreeStructure()
        new_tree.from_yaml(yaml_str)
        assert new_tree.root.id == "root"
        
    def test_empty_tree_serialization(self):
        """Test serialization of empty tree."""
        tree = TreeStructure()
        
        data = tree.to_dict()
        assert data["root"] is None
        
        json_str = tree.to_json()
        new_tree = TreeStructure()
        new_tree.from_json(json_str)
        assert new_tree.is_empty()


class TestTreeStructureNetworkX:
    """Test NetworkX integration."""
    
    def test_to_networkx(self):
        """Test conversion to NetworkX graph."""
        root = TreeNode(node_id="root", data={"type": "root"})
        child = TreeNode(node_id="child", data={"type": "child"})
        root.add_child(child)
        
        tree = TreeStructure(root)
        graph = tree.to_networkx()
        
        assert isinstance(graph, nx.DiGraph)
        assert "root" in graph.nodes
        assert "child" in graph.nodes
        assert ("root", "child") in graph.edges
        assert graph.nodes["root"]["type"] == "root"
        
    def test_from_networkx(self):
        """Test creation from NetworkX graph."""
        graph = nx.DiGraph()
        graph.add_node("root", type="root")
        graph.add_node("child", type="child")
        graph.add_edge("root", "child")
        
        tree = TreeStructure()
        tree.from_networkx(graph, "root")
        
        assert tree.root.id == "root"
        assert tree.root.get_data("type") == "root"
        assert len(tree.root.children) == 1
        assert tree.root.children[0].id == "child"
        
    def test_from_networkx_invalid_graph_raises_error(self):
        """Test that invalid graph raises error."""
        # Create graph with cycle
        graph = nx.DiGraph()
        graph.add_edge("a", "b")
        graph.add_edge("b", "a")
        
        tree = TreeStructure()
        with pytest.raises(InvalidNodeError):
            tree.from_networkx(graph, "a")


class TestTreeStructureConfiguration:
    """Test configuration-based creation."""
    
    def test_from_config(self):
        """Test creating tree from configuration."""
        config = {
            "metadata": {"version": "1.0"},
            "structure": {
                "id": "root",
                "data": {"type": "root"},
                "children": [
                    {"id": "child", "data": {"type": "child"}, "children": []}
                ]
            }
        }
        
        tree = TreeStructure.from_config(config)
        
        assert tree.root.id == "root"
        assert tree.get_metadata("version") == "1.0"
        assert len(tree.root.children) == 1
        
    def test_clone_tree(self):
        """Test cloning tree structure."""
        root = TreeNode(node_id="root", data={"key": "value"})
        child = TreeNode(node_id="child")
        root.add_child(child)
        
        tree = TreeStructure(root)
        tree.set_metadata("version", "1.0")
        
        cloned = tree.clone()
        
        assert cloned.root.id == "root"
        assert cloned.root.get_data("key") == "value"
        assert cloned.get_metadata("version") == "1.0"
        assert len(cloned.root.children) == 1
        
        # Verify it's a deep copy
        assert cloned.root is not tree.root
        assert cloned.root.children[0] is not tree.root.children[0]


class TestTreeStructureMagicMethods:
    """Test magic methods and operators."""
    
    def test_len(self):
        """Test __len__ method."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        root.add_child(child)
        
        tree = TreeStructure(root)
        assert len(tree) == 2
        
    def test_contains(self):
        """Test __contains__ method."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        root.add_child(child)
        
        tree = TreeStructure(root)
        assert "root" in tree
        assert "child" in tree
        assert "nonexistent" not in tree
        
    def test_iter(self):
        """Test __iter__ method."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        root.add_child(child)
        
        tree = TreeStructure(root)
        nodes = list(tree)
        assert len(nodes) == 2
        assert root in nodes
        assert child in nodes
        
    def test_str_and_repr(self):
        """Test string representations."""
        root = TreeNode(node_id="root")
        tree = TreeStructure(root)
        
        str_repr = str(tree)
        assert "TreeStructure" in str_repr
        assert "nodes=1" in str_repr
        
        repr_str = repr(tree)
        assert "TreeStructure" in repr_str
        assert "root=root" in repr_str


class TestTreeStructurePerformance:
    """Test performance with large trees."""
    
    def test_large_tree_operations(self):
        """Test operations on large tree (1000+ nodes)."""
        # Create a tree with 1000 nodes
        root = TreeNode(node_id="root")
        tree = TreeStructure(root)
        
        # Add nodes in a balanced way
        current_level = [root]
        node_count = 1
        
        while node_count < 1000:
            next_level = []
            for parent in current_level:
                for i in range(min(3, 1000 - node_count)):  # Max 3 children per node
                    child = TreeNode(node_id=f"node_{node_count}")
                    parent.add_child(child)
                    next_level.append(child)
                    node_count += 1
                    if node_count >= 1000:
                        break
                if node_count >= 1000:
                    break
            current_level = next_level
            
        # Test operations
        assert tree.get_node_count() >= 1000
        assert tree.get_depth() > 0
        
        # Test traversal
        nodes = list(tree.traverse_dfs())
        assert len(nodes) >= 1000
        
        # Test statistics
        stats = tree.get_statistics()
        assert stats["node_count"] >= 1000
        
        # Test serialization
        data = tree.to_dict()
        assert data["root"] is not None
