"""
Node Runner - Import & export shader nodes as shareable strings.

Serializes Blender shader node trees to compressed, base64-encoded
strings that can be shared via text, comments, or documentation, and
browses node setups published in git-backed library repositories.
"""

bl_info = {
    "name": "Node Runner",
    "description": "Import and export nodes as strings",
    "author": "Noah Thiering <noah.thiering@gmail.com>",
    "version": (1, 5, 0),
    "blender": (4, 5, 0),
    "category": "Node",
}


def register():
    """Register all operators, panels and menu entries."""
    from . import preferences, operators, node_data, library_ui

    node_data.refresh()
    # Preferences first: the repository PropertyGroup they own is referenced
    # by a CollectionProperty, which must be registered before its type.
    preferences.register()
    operators.register()
    library_ui.register()


def unregister():
    """Unregister all operators, panels and menu entries."""
    from . import preferences, operators, library_ui

    # Stops the library's timer and worker results first, so nothing fires
    # into a half-unloaded module.
    library_ui.unregister()
    operators.unregister()
    preferences.unregister()
