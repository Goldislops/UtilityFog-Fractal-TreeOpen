
"""
Unit tests for TreeNode class.

Tests cover node creation, parent-child relationships, data management,
and edge cases including circular reference prevention.
"""

import pytest
import uuid
import weakref
from src.fractal_tree import TreeNode, CircularReferenceError, InvalidNodeError


class TestTreeNodeCreation:
    """Test TreeNode creation and basic properties."""
    
    def test_create_node_with_default_id(self):
        """Test creating a node with auto-generated ID."""
        node = TreeNode()
        assert node.id is not None
        assert isinstance(node.id, str)
        assert len(node.id) > 0
        
    def test_create_node_with_custom_id(self):
        """Test creating a node with custom ID."""
        custom_id = "test-node-123"
        node = TreeNode(node_id=custom_id)
        assert node.id == custom_id
        
    def test_create_node_with_data(self):
        """Test creating a node with initial data."""
        data = {"key1": "value1", "key2": 42}
        node = TreeNode(data=data)
        assert node.get_data("key1") == "value1"
        assert node.get_data("key2") == 42
        
    def test_create_node_with_empty_id_raises_error(self):
        """Test that empty node ID raises InvalidNodeError."""
        with pytest.raises(InvalidNodeError):
            TreeNode(node_id="")
            
    def test_create_node_with_whitespace_id_raises_error(self):
        """Test that whitespace-only node ID raises InvalidNodeError."""
        with pytest.raises(InvalidNodeError):
            TreeNode(node_id="   ")
            
    def test_unique_ids_generated(self):
        """Test that auto-generated IDs are unique."""
        nodes = [TreeNode() for _ in range(100)]
        ids = [node.id for node in nodes]
        assert len(set(ids)) == 100  # All IDs should be unique


class TestTreeNodeDataManagement:
    """Test data storage and retrieval functionality."""
    
    def test_set_and_get_data(self):
        """Test setting and getting data values."""
        node = TreeNode()
        node.set_data("test_key", "test_value")
        assert node.get_data("test_key") == "test_value"
        
    def test_get_nonexistent_data_returns_default(self):
        """Test getting non-existent data returns default value."""
        node = TreeNode()
        assert node.get_data("nonexistent") is None
        assert node.get_data("nonexistent", "default") == "default"
        
    def test_remove_data(self):
        """Test removing data values."""
        node = TreeNode()
        node.set_data("test_key", "test_value")
        removed_value = node.remove_data("test_key")
        assert removed_value == "test_value"
        assert node.get_data("test_key") is None
        
    def test_remove_nonexistent_data_returns_none(self):
        """Test removing non-existent data returns None."""
        node = TreeNode()
        assert node.remove_data("nonexistent") is None
        
    def test_data_property_returns_copy(self):
        """Test that data property returns a copy, not reference."""
        node = TreeNode()
        node.set_data("key", "value")
        data_copy = node.data
        data_copy["key"] = "modified"
        assert node.get_data("key") == "value"  # Original unchanged


class TestTreeNodeRelationships:
    """Test parent-child relationship management."""
    
    def test_new_node_has_no_parent(self):
        """Test that new nodes have no parent."""
        node = TreeNode()
        assert node.parent is None
        assert node.is_root()
        
    def test_new_node_has_no_children(self):
        """Test that new nodes have no children."""
        node = TreeNode()
        assert len(node.children) == 0
        assert node.child_count == 0
        assert node.is_leaf()
        
    def test_add_child(self):
        """Test adding a child node."""
        parent = TreeNode()
        child = TreeNode()
        
        parent.add_child(child)
        
        assert child.parent == parent
        assert child in parent.children
        assert parent.child_count == 1
        assert not child.is_root()
        assert not parent.is_leaf()
        
    def test_add_multiple_children(self):
        """Test adding multiple children."""
        parent = TreeNode()
        children = [TreeNode() for _ in range(3)]
        
        for child in children:
            parent.add_child(child)
            
        assert parent.child_count == 3
        assert all(child.parent == parent for child in children)
        assert all(child in parent.children for child in children)
        
    def test_get_child_by_id(self):
        """Test retrieving child by ID."""
        parent = TreeNode()
        child = TreeNode(node_id="test-child")
        parent.add_child(child)
        
        retrieved = parent.get_child("test-child")
        assert retrieved == child
        
    def test_get_nonexistent_child_returns_none(self):
        """Test getting non-existent child returns None."""
        parent = TreeNode()
        assert parent.get_child("nonexistent") is None
        
    def test_has_child(self):
        """Test checking if child exists."""
        parent = TreeNode()
        child = TreeNode(node_id="test-child")
        
        assert not parent.has_child("test-child")
        parent.add_child(child)
        assert parent.has_child("test-child")
        
    def test_remove_child(self):
        """Test removing a child node."""
        parent = TreeNode()
        child = TreeNode(node_id="test-child")
        parent.add_child(child)
        
        removed = parent.remove_child("test-child")
        
        assert removed == child
        assert child.parent is None
        assert child not in parent.children
        assert parent.child_count == 0
        
    def test_remove_nonexistent_child_returns_none(self):
        """Test removing non-existent child returns None."""
        parent = TreeNode()
        assert parent.remove_child("nonexistent") is None
        
    def test_remove_from_parent(self):
        """Test removing node from its parent."""
        parent = TreeNode()
        child = TreeNode()
        parent.add_child(child)
        
        child.remove_from_parent()
        
        assert child.parent is None
        assert child not in parent.children
        assert parent.child_count == 0


class TestTreeNodeCircularReferenceProtection:
    """Test protection against circular references."""
    
    def test_cannot_add_self_as_child(self):
        """Test that node cannot be added as child of itself."""
        node = TreeNode()
        with pytest.raises(CircularReferenceError):
            node.add_child(node)
            
    def test_cannot_add_ancestor_as_child(self):
        """Test that ancestor cannot be added as child."""
        grandparent = TreeNode()
        parent = TreeNode()
        child = TreeNode()
        
        grandparent.add_child(parent)
        parent.add_child(child)
        
        # Try to add grandparent as child of child (would create cycle)
        with pytest.raises(CircularReferenceError):
            child.add_child(grandparent)
            
    def test_cannot_add_node_with_existing_parent(self):
        """Test that node with existing parent cannot be added elsewhere."""
        parent1 = TreeNode()
        parent2 = TreeNode()
        child = TreeNode()
        
        parent1.add_child(child)
        
        with pytest.raises(InvalidNodeError):
            parent2.add_child(child)
            
    def test_cannot_add_none_as_child(self):
        """Test that None cannot be added as child."""
        parent = TreeNode()
        with pytest.raises(InvalidNodeError):
            parent.add_child(None)


class TestTreeNodeTraversal:
    """Test tree traversal and search functionality."""
    
    def test_get_depth(self):
        """Test calculating node depth."""
        root = TreeNode()
        child = TreeNode()
        grandchild = TreeNode()
        
        root.add_child(child)
        child.add_child(grandchild)
        
        assert root.get_depth() == 0
        assert child.get_depth() == 1
        assert grandchild.get_depth() == 2
        
    def test_get_ancestors(self):
        """Test getting ancestor nodes."""
        root = TreeNode()
        child = TreeNode()
        grandchild = TreeNode()
        
        root.add_child(child)
        child.add_child(grandchild)
        
        ancestors = grandchild.get_ancestors()
        assert len(ancestors) == 2
        assert ancestors[0] == child
        assert ancestors[1] == root
        
    def test_get_descendants(self):
        """Test getting descendant nodes."""
        root = TreeNode()
        child1 = TreeNode()
        child2 = TreeNode()
        grandchild = TreeNode()
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        descendants = root.get_descendants()
        assert len(descendants) == 3
        assert child1 in descendants
        assert child2 in descendants
        assert grandchild in descendants
        
    def test_find_node(self):
        """Test finding node by ID in subtree."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child)
        child.add_child(grandchild)
        
        found = root.find_node("grandchild")
        assert found == grandchild
        
        assert root.find_node("nonexistent") is None
        
    def test_node_iteration(self):
        """Test iterating over nodes in subtree."""
        root = TreeNode()
        child1 = TreeNode()
        child2 = TreeNode()
        grandchild = TreeNode()
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        nodes = list(root)
        assert len(nodes) == 4
        assert root in nodes
        assert child1 in nodes
        assert child2 in nodes
        assert grandchild in nodes


class TestTreeNodeWeakReferences:
    """Test weak reference behavior for memory management."""
    
    def test_parent_reference_is_weak(self):
        """Test that parent references are weak and don't prevent GC."""
        parent = TreeNode()
        child = TreeNode()
        parent.add_child(child)
        
        # Store weak reference to parent
        parent_ref = weakref.ref(parent)
        
        # Delete parent
        del parent
        
        # Parent should be garbage collected
        import gc
        gc.collect()
        
        # Weak reference should be None
        assert parent_ref() is None
        
        # Child's parent should be None
        assert child.parent is None


class TestTreeNodeStringRepresentation:
    """Test string representation methods."""
    
    def test_str_representation(self):
        """Test __str__ method."""
        node = TreeNode(node_id="test-node")
        child = TreeNode()
        node.add_child(child)
        
        str_repr = str(node)
        assert "test-node" in str_repr
        assert "children=1" in str_repr
        
    def test_repr_representation(self):
        """Test __repr__ method."""
        node = TreeNode(node_id="test-node")
        node.set_data("key1", "value1")
        
        repr_str = repr(node)
        assert "test-node" in repr_str
        assert "parent=None" in repr_str
        assert "children=0" in repr_str
        assert "key1" in repr_str
