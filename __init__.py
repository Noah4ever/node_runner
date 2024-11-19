"""
This module adds the function to import and export
shader nodes from Blender.

It exports the shader nodes to a compressed and base64
encoded string that can be easily shared via a text
messager or comments in a video.
"""

import bpy
from . import node_runner_deserialize
from . import node_runner_serialize

bl_info = {
    "name": "Node Runner",
    "author": "Noah Thiering, Julius Ewert",
    "version": (0, 9, 10),
    "blender": (4, 2, 2),
    "location": "Node Editor Context Menu On Selected Nodes",
    "description": "Tool to easily import and export shader nodes as a string",
    "doc_url": "docs/",
    "category": "Node",
}

def register():
    """Register classes"""
    bpy.utils.register_class(node_runner_deserialize.NodeRunnerImportContextMenu)
    bpy.utils.register_class(node_runner_serialize.NodeRunnerExportContextMenu)

    bpy.utils.register_class(node_runner_deserialize.NodeRunnerImport)
    bpy.utils.register_class(node_runner_serialize.NodeRunnerExport)

    # Add it to the Shader Editor context menu
    bpy.types.NODE_MT_context_menu.append(node_runner_deserialize.menu_func_node_runner_import)
    bpy.types.NODE_MT_context_menu.append(node_runner_serialize.menu_func_node_runner_export)


def unregister():
    """Unregister classes"""
    bpy.types.NODE_MT_context_menu.remove(node_runner_serialize.menu_func_node_runner_export)
    bpy.types.NODE_MT_context_menu.remove(node_runner_deserialize.menu_func_node_runner_import)

    bpy.utils.unregister_class(node_runner_serialize.NodeRunnerExport)
    bpy.utils.unregister_class(node_runner_deserialize.NodeRunnerImport)

    bpy.utils.unregister_class(node_runner_serialize.NodeRunnerExportContextMenu)
    bpy.utils.unregister_class(node_runner_deserialize.NodeRunnerImportContextMenu)

if __name__ == "__main__":
    register()
