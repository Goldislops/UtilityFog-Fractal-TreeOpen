"""
Custom exceptions for the Fractal Tree system.
"""


class TreeNodeError(Exception):
    """Base exception for all tree node related errors."""

    pass


class CircularReferenceError(TreeNodeError):
    """Raised when a circular reference is detected in the tree structure."""

    pass


class InvalidNodeError(TreeNodeError):
    """Raised when an invalid node operation is attempted."""

    pass


class NodeNotFoundError(TreeNodeError):
    """Raised when a requested node cannot be found."""

    pass
