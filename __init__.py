"""
Node Runner - Import & export shader, geometry, and compositor nodes as shareable strings.

Serializes Blender shader, geometry, and compositor node trees to compressed, base64-encoded
strings that can be shared via text, comments, or documentation.
"""

bl_info = {
    "name": "Node Runner",
    "description": "Import and export nodes as strings",
    "author": "Noah Thiering <noah.thiering@gmail.com>",
    "version": (1, 4, 7),
    "blender": (4, 2, 0),
    "category": "Node",
}


def register():
    """Register all operators and menu entries."""
    from . import operators, node_data

    node_data.refresh()
    operators.register()


def unregister():
    """Unregister all operators and menu entries."""
    from . import operators

    operators.unregister()
