"""
This module provides serialize functions and classes for node runner.
"""

import pickle
import zlib
import base64
import bpy
import mathutils

def serialize_color(color):
    """Serialize color

    Args:
      color: Color to serialize
    Returns:
      Serialized color as list
    """
    return list(color)

def serialize_vector(vector):
    """Serialize vector

    Args:
      vector: Vector to serialize
    Returns:
      Serialized vector as list
    """
    return list(vector)

def serialize_euler(euler):
    """Serialize euler

    Args:
      euler: Euler to serialize
    Returns:
      Serialized euler as list
    """
    return list(euler)

def serialize_color_ramp(node):
    """Serialize color ramp

    Args:
      node: Node to serialize
    Returns:
      Serialized color ramp data
    """
    data = {
        "color_mode": node.color_ramp.color_mode,
        "elements": [],
        "hue_interpolation": node.color_ramp.hue_interpolation,
        "interpolation": node.color_ramp.interpolation,
    }
    for element in node.color_ramp.elements:
        data["elements"].append(
            {"position": element.position, "color": list(element.color)}
        )
    return data

def serialize_color_mapping(node):
    """Serialize color mapping

    Args:
      node: Node to serialize
    Returns:
      Serialized color mapping data
    """
    return {
        "blend_color": serialize_color(node.color_mapping.blend_color),
        "blend_factor": node.color_mapping.blend_factor,
        "blend_type": node.color_mapping.blend_type,
        "brightness": node.color_mapping.brightness,
        "color_ramp": serialize_color_ramp(node.color_mapping),
        "contrast": node.color_mapping.contrast,
        "saturation": node.color_mapping.saturation,
        "use_color_ramp": node.color_mapping.use_color_ramp,
    }

def serialize_texture_mapping(node):
    """Serialize texture mapping

    Args:
      node: Node to serialize
    Returns:
      Serialized texture mapping data
    """
    return {
        "mapping": node.texture_mapping.mapping,
        "mapping_x": node.texture_mapping.mapping_x,
        "mapping_y": node.texture_mapping.mapping_y,
        "mapping_z": node.texture_mapping.mapping_z,
        "max": serialize_vector(node.texture_mapping.max),
        "min": serialize_vector(node.texture_mapping.min),
        "rotation": serialize_vector(node.texture_mapping.rotation),
        "scale": serialize_vector(node.texture_mapping.scale),
        "translation": serialize_vector(node.texture_mapping.translation),
        "use_max": node.texture_mapping.use_max,
        "use_min": node.texture_mapping.use_min,
        "vector_type": node.texture_mapping.vector_type,
    }

def serialize_curve_mapping(node):
    """Serialize curve mapping

    Args:
      node: Node to serialize
    Returns:
      Serialized curve mapping data
    """
    return {
        "black_level": serialize_attr(node, node.mapping.black_level),
        "clip_max_x": node.mapping.clip_max_x,
        "clip_max_y": node.mapping.clip_max_y,
        "clip_min_x": node.mapping.clip_min_x,
        "clip_min_y": node.mapping.clip_min_y,
        "curves": serialize_attr(node, node.mapping.curves),
        "extend": node.mapping.extend,
        "tone": node.mapping.tone,
        "use_clip": node.mapping.use_clip,
        "white_level": serialize_attr(node, node.mapping.white_level),
    }

def serialize_curve_map(node, curve_map: bpy.types.CurveMap):
    """Serialize curve map

    Args:
      node: Node to serialize
      curve_map: Curve map to serialize
      curve_map: bpy.types.CurveMap:
    Returns:
      Serialized curve map data
    """
    return {
        "points": serialize_attr(node, curve_map.points),
    }

def serialize_curve_map_point(node, curve_map_point: bpy.types.CurveMapPoint):
    """Serialize curve map point

    Args:
      node: Node to serialize
      curve_map_point: Curve map point to serialize
      curve_map_point: bpy.types.CurveMapPoint:
    Returns:
      Serialized curve map point data
    """
    return {
        "handle_type": curve_map_point.handle_type,
        "location": serialize_attr(node, curve_map_point.location),
        "select": curve_map_point.select,
    }

def serialize_image(image: bpy.types.Image):
    """Serialize image.

    Args:
      node: Node to serialize.
      image(bpy.types.Image): Image to serialize.
      image: bpy.types.Image:
    Returns:
      dict: Serialized image data.
    """
    return {
        "name": image.name,
    }

def serialize_text_line(text: bpy.types.TextLine):
    """Serialize text line

    Args:
        text: Text line to serialize
    Returns:
        Serialized text line data
    """
    return {
        "body": text.body,
    }

def serialize_text(text: bpy.types.Text):
    """Serialize text

    Args:
      text: Text to serialize
    Returns:
      Serialized text data
    """

    serializes_lines = []
    for line in text.lines:
        serializes_lines.append(serialize_text_line(line))

    return {
        "current_character": text.current_character,
        "current_line": serialize_text_line(text.current_line),
        "current_line_index": text.current_line_index,
        "filepath": text.filepath,
        "indentation": text.indentation,
        "lines": serializes_lines,
        "select_end_character": text.select_end_character,
        "select_end_line_index": text.select_end_line_index,
        "use_module": text.use_module,
    }

def serialize_node_frame(node: bpy.types.NodeFrame):
    """Serialize node frame

    Args:
      node: Node to serialize
    Returns:
      Serialized node frame data
    """
    return {
        "label_size": node.label_size,
        "shrink": node.shrink,
        "text": serialize_text(node.text),
    }

def serialize_attr(node, attr):
    """Serialize attribute of a node

    Check the type of the attribute and serialize it accordingly.
    If the attribute is a complex type, call the corresponding serialization function.
    Prints an error message if the serialization fails.

    Args:
      node: Node to serialize
      attr: Attribute to serialize
    Returns:
      Serialized attribute data
    """
    serializers = {
        mathutils.Color: serialize_color,
        mathutils.Vector: serialize_vector,
        mathutils.Euler: serialize_euler,
        bpy.types.ColorRamp: lambda d: serialize_color_ramp(node),
        bpy.types.ShaderNodeTree: lambda d: serialize_node_tree(node.node_tree),
        bpy.types.ColorMapping: lambda d: serialize_color_mapping(node),
        bpy.types.TexMapping: lambda d: serialize_texture_mapping(node),
        bpy.types.CurveMapping: lambda d: serialize_curve_mapping(node),
        bpy.types.CurveMap: lambda d: serialize_curve_map(node, d),
        bpy.types.CurveMapPoint: lambda d: serialize_curve_map_point(node, d),
        bpy.types.Image: serialize_image,
        bpy.types.ImageUser: lambda d: {},
        bpy.types.NodeFrame: lambda d: serialize_node_frame(node),
        bpy.types.Text: lambda d: serialize_text(node.script),
        bpy.types.Object: lambda d: None,
        bpy.types.NodeSocketStandard: lambda d: (
            serialize_attr(node, d.default_value)
            if hasattr(d, "default_value")
            else None
        ),
        bpy.types.bpy_prop_collection: lambda d: [
            serialize_attr(node, element) for element in d.values()
        ],
        bpy.types.bpy_prop_array: lambda d: [
            serialize_attr(node, element) for element in d
        ],
    }

    for data_type, serializer in serializers.items():
        if isinstance(attr, data_type):
            return serializer(attr)
    try:
        pickle.dumps(attr)  # Try to pickle dump to get error message
    except (pickle.PicklingError, TypeError, AttributeError, EOFError):
        print(
            "[ERROR] Serializing error on:",
            node.name,
            "with data:",
            attr,
            "and type:",
            type(attr),
        )
        return None
    return attr

def serialize_node(node):
    """Serialize node properties

    Loop through all properties of the node and serialize them and add them to a dictionary.

    Args:
      node: Node to serialize
    Returns:
      Serialized node dictionary
    """
    exclude_props = [
        "__doc__",
        "__module__",
        "__slots__",
        "__slotnames__",
        "bl_description",
        "bl_height_default",
        "bl_height_max",
        "bl_height_min",
        "bl_icon",
        "bl_idname",
        "bl_label",
        "bl_rna",
        "bl_static_type",
        "bl_width_default",
        "bl_width_max",
        "bl_width_min",
        "cache_point_density",
        "calc_point_density",
        "calc_point_density_minmax",
        "dimensions",
        "draw_buttons",
        "draw_buttons_ext",
        "hide",
        "input_template",
        "internal_links",
        "is_registered_node_type",
        "label",
        "output_template",
        "poll",
        "poll_instance",
        "rna_type",
        "select",
        "socket_value_update",
        "type",
        "update",
        "debug_zone_body_lazy_function_graph",
        "debug_zone_lazy_function_graph"
    ]

    node_dict = {}

    for prop in [p for p in dir(node) if p not in exclude_props]:
        attr = getattr(node, prop)
        if attr is None:
            continue
        if prop == "parent":
            # Serialize parent node name for NodeFrame's
            node_dict["parent"] = node.parent.name
            continue
        if node.bl_idname in ("NodeGroupInput", "NodeGroupOutput"):
            if prop == "inputs":
                node_dict["input_order"] = []
                for _, puts in enumerate(node.inputs):
                    if puts.bl_idname == "NodeSocketVirtual":
                        continue
                    node_dict["input_order"].append({"type": puts.bl_idname,
                                                     "name": puts.name,
                                                     "identifier": puts.identifier})
            if prop == "outputs":
                node_dict["output_order"] = []
                for i, puts in enumerate(node.outputs):
                    if puts.bl_idname == "NodeSocketVirtual":
                        continue
                    node_dict["output_order"].append({"type": puts.bl_idname,
                                                      "name": puts.name,
                                                      "identifier": puts.identifier})
        node_dict[prop] = serialize_attr(node, attr)
    node_dict["type"] = node.bl_idname
    node_dict["label"] = node.label
    return node_dict

def serialize_node_tree(node_tree, selected_node_names=None):
    """Serialize node tree

    Loop through all nodes and links of the node tree and serialize them.

    Args:
      node_tree: Node tree to serialize
      selected_node_names: Selected node names (Default value = None)
    Returns:
      Serialized node tree data
    """
    nodes = node_tree.nodes

    # Initialize empty data structure for nodes and links
    data = {"nodes": {}, "links": []}
    selected_nodes = []
    if selected_node_names is None:
        selected_nodes = list(node_tree.nodes)
    else:
        for node_name in selected_node_names:
            if node_name in nodes:
                selected_nodes.append(nodes[node_name])

    # Serialize selected nodes
    for node in selected_nodes:
        node_dict = serialize_node(node)
        data["nodes"][node.name] = node_dict

    # Save links (only for selected nodes)
    for link in node_tree.links:
        if link.from_node in selected_nodes and link.to_node in selected_nodes:
            data["links"].append(
                {
                    "from_node": link.from_node.name,
                    "to_node": link.to_node.name,
                    "from_socket": link.from_socket.name,
                    "from_socket_type": link.from_socket.bl_idname,
                    "from_socket_identifier": link.from_socket.identifier,
                    "to_socket": link.to_socket.name,
                    "to_socket_type": link.to_socket.bl_idname,
                    "to_socket_identifier": link.to_socket.identifier,
                }
            )
    data["name"] = node_tree.name
    return data

def encode_data(node_tree, selected_node_names=None):
    """Encode data

    Serialize the node tree and compress and encode the data with zlib and base64.

    Args:
      node_tree: Node tree to encode
      selected_node_names: Selected node names (Default value = None)
    Returns:
      Base64 encoded data
    """
    # Serialize node tree
    data = serialize_node_tree(node_tree, selected_node_names)
    print(" DADADADA:", data)
    # Compress and encode data
    compress_data = zlib.compress(pickle.dumps(data), 9)
    base64_encoded = base64.b64encode(compress_data).decode("utf-8")

    print(base64_encoded)
    print(len(base64_encoded))
    return base64_encoded

class NodeRunnerExport(bpy.types.Operator):
    """Class for export dialog"""

    bl_idname = "object.node_runner_export"
    bl_label = "Node Runner Export"
    bl_options = {"REGISTER", "UNDO"}

    node_runner_export_field: bpy.props.StringProperty(
        name="Node Runner Hash String",
        default="",
        description="Node Runner Hash String",
    )  # type: ignore

    # pylint: disable=unused-argument
    def execute(self, context):
        """
        Args:
          self:
          context:
        Returns:
        """

        return {"FINISHED"}

    # pylint: disable=unused-argument
    def draw(self, context):
        """
        Args:
          self:
          context:
        Returns:
        """
        layout = self.layout

        # Show some text
        layout.label(text="Hash has been copied to clipboard")

        # Create the input field
        layout.prop(self, "node_runner_export_field", text="Export Field")

    # pylint: disable=unused-argument
    def invoke(self, context, event):
        """
        Args:
          self:
          context:
          event:
        Returns:
        """
        wm = context.window_manager
        material = bpy.context.object.active_material
        if not material or not hasattr(material, "node_tree"):
            self.report({"INFO"}, "No valid material with a node tree selected")
            return {"CANCELLED"}

        selected_nodes = bpy.context.selected_nodes
        selected_node_names = []
        for node in selected_nodes:
            # NodeGroupInput and NodeGroupOutput are generated automatically by a
            # NodeGroup and cannot be exported/imported
            if selected_nodes and not isinstance(node,
                                                 (bpy.types.NodeGroupInput,
                                                  bpy.types.NodeGroupOutput)):
                selected_node_names.append(node.name)

        compress_nodes = encode_data(
            bpy.context.space_data.edit_tree, selected_node_names=selected_node_names
        )
        self.report({"INFO"}, "Node Runner Hash copied to clipboard")

        compress_nodes_with_header = "YourNodeName__NR" + compress_nodes

        self.node_runner_export_field = compress_nodes_with_header
        bpy.context.window_manager.clipboard = compress_nodes_with_header
        return wm.invoke_props_dialog(self)

class NodeRunnerExportContextMenu(bpy.types.Operator):
    """Class for export option in context menu"""

    bl_idname = "object.node_runner_export_context_menu"
    bl_label = "Node Runner Export Context Menu"

    # pylint: disable=unused-argument
    def execute(self, context):
        """
        Args:
          self:
          context:
        Returns:
        """
        selected_nodes = bpy.context.selected_nodes
        selected_node_names = (
            [node.name for node in selected_nodes] if selected_nodes else None
        )

        if selected_node_names is None:
            self.report({"WARNING"}, "No nodes selected!")
            return {"CANCELLED"}

        nodes = bpy.context.space_data.edit_tree.nodes
        i = 0
        for selected_node in selected_node_names:
            if not isinstance(nodes[selected_node],
                              (bpy.types.NodeGroupInput, bpy.types.NodeGroupOutput)):
                i += 1
        if i == 0:
            self.report({"WARNING"}, "No valid nodes selected!")
            return {"CANCELLED"}

        bpy.ops.object.node_runner_export("INVOKE_DEFAULT")
        return {"FINISHED"}

    # pylint: disable=unused-argument
    def invoke(self, context, event):
        """
        Args:
          self:
          context:
          event:
        Returns:
        """
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

# pylint: disable=unused-argument
def menu_func_node_runner_export(self, context):
    """
    Args:
      self:
      context:
    Returns:
    """
    self.layout.operator(
        NodeRunnerExportContextMenu.bl_idname, text="Node Runner Export"
    )
