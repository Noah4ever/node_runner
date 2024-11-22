"""
This module provides deserialize functions and classes for node runner.
"""

import binascii
import pickle
import zlib
import base64
import bpy

def deserialize_color_ramp(node, data):
    """Deserialize color ramp

    Args:
      node: Node to set color ramp data
      data: Data to deserialize
    Returns:
    """
    node.color_ramp.color_mode = data.get("color_mode", 0)
    node.color_ramp.hue_interpolation = data.get("hue_interpolation", 1)
    node.color_ramp.interpolation = data.get("interpolation", 2)

    for i, element_data in enumerate(data["elements"]):
        element = node.color_ramp.elements[i]
        element.position = element_data["position"]
        element.color = element_data["color"]

def deserialize_color_mapping(node, data):
    """Deserialize color mapping

    Args:
      node: Node to set color mapping data
      data: Data to deserialize
    Returns:
    """
    node.color_mapping.blend_color = data.get("blend_color", (0.0, 0.0, 0.0))
    node.color_mapping.blend_factor = data.get("blend_factor", 0.0)
    node.color_mapping.blend_type = data.get("blend_type", 0)
    node.color_mapping.brightness = data.get("brightness", 0.0)
    deserialize_color_ramp(node.color_mapping, data["color_ramp"])
    node.color_mapping.contrast = data.get("contrast", 0)
    node.color_mapping.saturation = data.get("saturation", 0)
    node.color_mapping.use_color_ramp = data.get("use_color_ramp", 0)

def deserialize_texture_mapping(node, data):
    """Deserialize texture mapping

    Args:
      node: Node to set texture mapping data
      data: Data to deserialize
    Returns:
    """
    node.texture_mapping.mapping = data.get("mapping", 0)
    node.texture_mapping.mapping_x = data.get("mapping_x", 0)
    node.texture_mapping.mapping_y = data.get("mapping_y", 0)
    node.texture_mapping.mapping_z = data.get("mapping_z", 0)
    node.texture_mapping.max = data.get("max", (0.0, 0.0, 0.0))
    node.texture_mapping.min = data.get("min", (0.0, 0.0, 0.0))
    node.texture_mapping.rotation = data.get("rotation", (0.0, 0.0, 0.0))
    node.texture_mapping.scale = data.get("scale", (0.0, 0.0, 0.0))
    node.texture_mapping.translation = data.get("translation", (0.0, 0.0, 0.0))
    node.texture_mapping.use_max = data.get("use_max", False)
    node.texture_mapping.use_min = data.get("use_min", False)
    node.texture_mapping.vector_type = data.get("vector_type", 0)

def deserialize_inputs(node, data, node_data, node_tree, node_group_socket_identifier):
    """Deserialize inputs

    Check if the node has inputs and set the input values.

    Args:
      node: Node to set inputs
      data: Data to deserialize
    Returns:
    """
    # Inputs of NodeGroupInput and NodeGroupOutput cannot be set on the node
    # but need to be set on the group instead
    if isinstance(node, (bpy.types.NodeGroupInput, bpy.types.NodeGroupOutput)):
        if isinstance(node, bpy.types.NodeGroupInput):
            for input_data in node_data["output_order"]:
                input_interface_socket: bpy.types.NodeTreeInterfaceSocket = create_socket(
                    node_tree,
                    input_data["name"],
                    input_data["name"] + " Input",
                    "INPUT",
                    get_node_socket_base_type(input_data["type"]),
                )
                node_group_socket_identifier[input_data["identifier"]] = input_interface_socket.identifier
        return

    for i, input_value in enumerate(data):
        if (
            input_value is not None
            and hasattr(node, "inputs")
            and len(node.inputs) > 0
            and hasattr(node.inputs[i], "default_value")
        ):
            node.inputs[i].default_value = input_value

def deserialize_outputs(node, data, node_data, node_tree, node_group_socket_identifier):
    """Deserialize outputs

    Check if the node has outputs and set the output values.

    Args:
      node: Node to set outputs
      data: Data to deserialize
    Returns:
    """
    # Output of NodeGroupInput and NodeGroupOutput cannot be set on the node
    # but need to be set on the group instead
    if isinstance(node, (bpy.types.NodeGroupInput, bpy.types.NodeGroupOutput)):
        if isinstance(node, bpy.types.NodeGroupOutput):
            for output_data in node_data["input_order"]:
                output_interface_socket: bpy.types.NodeTreeInterfaceSocket = create_socket(
                    node_tree,
                    output_data["name"],
                    output_data["name"] + " Output",
                    "OUTPUT",
                    get_node_socket_base_type(output_data["type"]),
                )
                node_group_socket_identifier[output_data["identifier"]] = output_interface_socket.identifier
        return

    for i, output in enumerate(data):
        if (
            output is not None
            and hasattr(node, "outputs")
            and len(node.outputs) > 0
            and hasattr(node.outputs[i], "default_value")
        ):
            node.outputs[i].default_value = output

def deserialize_curve_mapping(node, data):
    """Deserialize curve mapping

    Args:
      node: Node to set curve mapping data
      data: Data to deserialize
    Returns:
    """
    node.mapping.black_level = data.get("black_level", (0.0, 0.0, 0.0))

    i = 0
    for curve_map in data.get("curves", 0):

        j = 0
        # Set first and last point because by default there are two points in a new curve
        for point in node.mapping.curves[i].points:
            point.location = curve_map.get("points")[j].get("location", (0.0, 0.0))
            j -= 1

        # Create and set the rest of the points
        for k in  range(1, len(curve_map.get("points")) - 1):
            location = curve_map.get("points")[k].get("location", (0.0, 0.0))
            node.mapping.curves[i].points.new(location[0], location[1])
        i += 1

    node.mapping.clip_max_x = data.get("clip_max_x", 0)
    node.mapping.clip_max_y = data.get("clip_max_y", 0)
    node.mapping.clip_min_x = data.get("clip_min_x", 0)
    node.mapping.clip_min_y = data.get("clip_min_y", 0)

    node.mapping.extend = data.get("extend", 0)
    node.mapping.tone = data.get("tone", 0)
    node.mapping.use_clip = data.get("use_clip", 0)
    node.mapping.white_level = data.get("white_level", (0.0, 0.0, 0.0))

def deserialize_image(node, data):
    """Deserialize image

    Args:
      node: Node to set image data
      data: Data to deserialize
    Returns:
    """
    image = next(
        (obj for obj in bpy.context.blend_data.images if obj.name == data.get("name")),
        None,
    )
    if not image:
        return
    node.image = image

def deserialize_text_line(text_line, data):
    """Deserialize text line

    Args:
      node: Node to set text line data
      data: Data to deserialize
    Returns:
    """
    text_line.body = data.get("body", "")

def deserialize_text(data):
    """Deserialize text

    Args:
      node: Node to set text data
      data: Data to deserialize
    Returns:
    """

    # if data.filepath can be found in bpy.data.texts, use that text
    text = next(
        (
            obj
            for obj in bpy.context.blend_data.texts
            if obj.filepath == data.get("filepath")
        ),
        None,
    )
    if text:
        return text

    text = bpy.data.texts.new(name="Text")
    text.current_character = data.get("current_character", 0)
    deserialize_text_line(text.current_line, data.get("current_line", {}))
    text.current_line_index = data.get("current_line_index", 0)
    text.filepath = data.get("filepath", "")
    text.indentation = data.get("indentation", 0)
    text.select_end_character = data.get("select_end_character", 0)
    text.select_end_line_index = data.get("select_end_line_index", 0)
    text.use_module = data.get("use_module", False)

    return text

#pylint: disable=too-many-branches
def deserialize_node(node_data, node_tree, node_group_socket_identifier):
    """Deserialize node

    Loop through all properties of the node data and deserialize them accordingly.

    Args:
      node_data: Node data to deserialize
      nodes: Nodes to add the new node to
    Returns:
      New node
    """
    if node_data["type"] == "NodeUndefined":
        return None

    new_node = node_tree.nodes.new(type=node_data["type"])  # Create new node
    new_node.label = node_data["label"]  # Set node label

    # Node tree has to be done before other properties like inputs and outputs
    if "node_tree" in node_data:
        new_node.node_tree = bpy.data.node_groups.new(node_data["node_tree"]["name"],
                                                      "ShaderNodeTree")
        deserialize_node_tree(new_node.node_tree, node_data["node_tree"])
        node_data.pop("node_tree")

    readonly_props = ["type", "image_user"]
    for prop_name, prop_value in node_data.items():
        if prop_name in readonly_props:
            continue
        # Special handling for complex types
        if prop_name == "color_ramp":
            deserialize_color_ramp(new_node, prop_value)
        elif prop_name == "color_mapping":
            deserialize_color_mapping(new_node, prop_value)
        elif prop_name == "texture_mapping":
            deserialize_texture_mapping(new_node, prop_value)
        elif prop_name == "mapping":
            deserialize_curve_mapping(new_node, prop_value)
        elif prop_name == "image":
            deserialize_image(new_node, prop_value)
        elif prop_name == "inputs":
            deserialize_inputs(new_node, prop_value, node_data, node_tree, node_group_socket_identifier)
        elif prop_name == "outputs":
            deserialize_outputs(new_node, prop_value, node_data, node_tree, node_group_socket_identifier)
        elif prop_name == "script":
            new_node.script = deserialize_text(prop_value)
        elif prop_name == "parent" and prop_value in node_tree.nodes:
            new_node.parent = node_tree.nodes[prop_value]
        else:
            try:
                setattr(new_node, prop_name, prop_value)
            except (TypeError, AttributeError, EOFError):
                print(
                    "[ERROR] Setting attribute on:",
                    new_node.name,
                    "with attribute:",
                    prop_name,
                    "and attribute value:",
                    prop_value,
                )
    return new_node

def get_node_socket_base_type(socket_type):
    """Get base type of node socket.

    This is used to create new sockets on the ShaderNodeGroup.
    Only base types can be used for creating a new socket on the ShaderNodeGroup.

    Args:
      type: str
    Returns:
      str: Base type of node socket
    """
    usable_type_array = [
        "NodeSocketBool",
        "NodeSocketVector",
        "NodeSocketInt",
        "NodeSocketShader",
        "NodeSocketFloat",
        "NodeSocketColor",
    ]
    for usable_type in usable_type_array:
        if usable_type in socket_type:
            return usable_type
    return usable_type_array[0]

def get_socket_by_identifier(node, identifier, node_group_socket_identifier, socket_type="INPUT"):
    """Get socket by identifier

    Loops through the input or output sockets of a node and
    returns the socket with the given identifier.

    Args:
      node: Node to get the socket from
      identifier: Identifier of the socket
      socket_type:  (Default value = "INPUT")
    Returns:
      Socket with the given identifier
    """
    # Select input or output sockets
    sockets = node.inputs if socket_type.upper() == "INPUT" else node.outputs
    internal_identifier = identifier
    # Find the socket by identifier
    if node.bl_idname == "NodeGroupOutput" or node.bl_idname == "NodeGroupInput":
        internal_identifier = node_group_socket_identifier[identifier]
    for socket in sockets:
        if socket.identifier == internal_identifier:
            return socket
    return None

def create_socket(node_tree, socket_name, description, in_out, socket_type):
    """Create new socket on the ShaderNodeGroup

    Args:
      node_tree: Node tree to create the socket on
      socket_name: Name of the socket
      description: Description of the socket
      in_out: INPUT" or "OUTPUT"
      socket_type: Type of the socket
    Returns:
      New socket
    """
    return node_tree.interface.new_socket(
        name=socket_name,
        description=description,
        in_out=in_out,
        socket_type=socket_type,
    )

def deserialize_link(node_tree, node_names, link_data, node_group_socket_identifier):
    """Deserialize link

    Deserialize the link data.
    If the link is connected to a NodeGroupInput or NodeGroupOutput, create
    a new input or output socket on the ShaderNodeGroup.

    Args:
      node: Node to deserialize the link on
      node_names: Dictionary with node names
      link_data: Link data to deserialize
    Returns:
      Output and input socket of the link
    """
    if (
        node_names[link_data["from_node"]] is None
        or node_names[link_data["to_node"]] is None
    ):
        print("[ERROR] Node not found")
        return None, None

    # === From node ===
    from_node = node_names[link_data["from_node"]]
    output_socket = get_socket_by_identifier(
        from_node, link_data["from_socket_identifier"], node_group_socket_identifier, "OUTPUT"
    )

    # if from_node.bl_idname == "NodeGroupInput":
    #     # Create new input socket on the ShaderNodeGroup
    #     if output_socket is None:
    #         output_interface_socket: bpy.types.NodeTreeInterfaceSocket = create_socket(
    #             node_tree,
    #             link_data["from_socket"],
    #             link_data["from_socket"] + " Input",
    #             "INPUT",
    #             get_node_socket_base_type(link_data["to_socket_type"]),
    #         )
    #         output_socket = get_socket_by_identifier(
    #             from_node, output_interface_socket.identifier, "OUTPUT"
    #         )

    # === To node ===
    to_node = node_names[link_data["to_node"]]
    input_socket = get_socket_by_identifier(
        to_node, link_data["to_socket_identifier"], node_group_socket_identifier, "INPUT"
    )
    # if to_node.bl_idname == "NodeGroupOutput":
    #     # Create new output socket on the ShaderNodeGroup
    #     if input_socket is None:
    #         input_interface_socket: bpy.types.NodeTreeInterfaceSocket = create_socket(
    #             node_tree,
    #             link_data["to_socket"],
    #             link_data["to_socket"] + " Output",
    #             "OUTPUT",
    #             get_node_socket_base_type(link_data["from_socket_type"]),
    #         )
    #         input_socket = get_socket_by_identifier(
    #             to_node, input_interface_socket.identifier, "INPUT"
    #         )

    return output_socket, input_socket

def build_node_parent_name_map(data, node_tree):
    """
    Build a mapping of old node names to new node names (for frames).

    Args:
        data: Serialized data containing the node structure.
        node_tree: The node tree where new nodes will be added.

    Returns:
        node_parent_name: A dictionary mapping old node names to new names.
    """
    node_parent_name = {}
    node_frame_location = {}

    # Create nodes for frames first to ensure they exist
    for node_name, node_data in data["nodes"].items():
        if node_data["type"] == "NodeFrame":
            new_node = deserialize_node(node_data, node_tree.nodes)
            new_node.name = node_data["name"]

            # If the name was changed, map the old name to the new name
            if new_node.name != node_name:
                node_parent_name[node_name] = new_node.name
            else:
                node_parent_name[node_name] = node_name

            node_frame_location[node_parent_name[node_name]] = new_node.location
            #new_node.location = [0, 0]

    # Remove the frame nodes from the node list
    for node_name in node_parent_name:
        data["nodes"].pop(node_name)

    return node_parent_name, node_frame_location

def update_parent_references(data, node_parent_name):
    """
    Update the parent references in the serialized node data based on the new node names.

    Args:
        data: Serialized data containing the node structure.
        node_parent_name: A mapping from old node names to new node names.
    """
    for _, node_data in data["nodes"].items():
        # Check if the node has a parent frame
        if "parent" in node_data and node_data["parent"] in node_parent_name:
            # Update the parent frame to the new name
            node_data["parent"] = node_parent_name[node_data["parent"]]

def deserialize_node_tree(node_tree, data):
    """Deserialize node tree

    Deserialize the node tree data and create new nodes and links.

    Args:
      node: Node to deserialize the node tree on
      data: Data to deserialize
    Returns:
    """
    node_names = {}

    node_group_socket_identifier = {}

    node_parent_name = {}
    node_frame_location = {}

    node_parent_name, node_frame_location = build_node_parent_name_map(data, node_tree)

    update_parent_references(data, node_parent_name)

    # Save the new node with the node name which is used for linking to get the node
    for node_name, node_data in data["nodes"].items():
        node_names[node_name] = deserialize_node(node_data, node_tree, node_group_socket_identifier)
        # Setting correct location for frames
        if node_names[node_name].parent and isinstance(node_names[node_name].parent,
                                                       bpy.types.NodeFrame):
            node_frame_name = node_names[node_name].parent.name
            if node_frame_name in node_frame_location:
                location = node_frame_location[node_frame_name]
                node_names[node_name].location = node_names[node_name].location + location
            else:
                # Remove parent from created node if its not inside the current deserialized nodes
                node_names[node_name].parent = None

    # Apply links
    for link_data in data["links"]:
        # Deserialize link
        output_socket, input_socket  = deserialize_link(node_tree, node_names, link_data, node_group_socket_identifier)
        # Create new link
        if input_socket and output_socket:
            node_tree.links.new(input_socket, output_socket)

def decode_data(base64_encoded, material):
    """Decode data

    Decode and decompress the base64 encoded data and deserialize the data.

    Args:
      base64_encoded: Base64 encoded data
      material: Material to set the node tree on
    Returns:
      Result of the operation: ("FINISHED", "Node Runner Import executed")
    """

    # Create new material if none is selected
    if not material or not hasattr(material, "node_tree"):
        material = bpy.data.materials.new(name="Material")
        if bpy.context.active_object:
            bpy.context.active_object.data.materials.append(material)

    # Decode base64 encoded data
    try:
        decompressed_data = zlib.decompress(base64.b64decode(base64_encoded))
        deserialized_data = pickle.loads(decompressed_data)
        print(deserialized_data)
    except (zlib.error, pickle.UnpicklingError, binascii.Error):
        return ("CANCELLED", "Decoding error")
    #pylint: disable=broad-exception-caught
    except (Exception,) as e:
        return ("CANCELLED", f"Decoding error: {e}")


    # Deserialize node tree
    deserialize_node_tree(bpy.context.space_data.edit_tree, deserialized_data)
    return ("FINISHED", "Node Runner Import executed")

class NodeRunnerImport(bpy.types.Operator):
    """Class for import dialog"""

    bl_idname = "object.node_runner_import"
    bl_label = "Node Runner Import"
    bl_options = {"REGISTER", "UNDO"}

    my_node_runner_string: bpy.props.StringProperty(
        name="Node Runner Hash",
        default="",
        description="Node Runner Hash",
    )  # type: ignore

    # pylint: disable=unused-argument
    def execute(self, context):
        """
        Args:
          self:
          context:
        Returns:
        """
        if self.my_node_runner_string == "":
            self.report({"INFO"}, "No Node Runner Hash String provided")
            return {"CANCELLED"}

        result = decode_data(self.my_node_runner_string.split("__NR", 1)[1], bpy.context.material)

        self.report({"INFO"}, result[1])
        return {result[0]}

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

class NodeRunnerImportContextMenu(bpy.types.Operator):
    """Class for import option in context menu"""

    bl_idname = "object.node_runner_import_context_menu"
    bl_label = "Node Runner Import Context Menu"

    # pylint: disable=unused-argument
    def execute(self, context):
        """Checks for a valid material and node tree and invokes
        the import dialog
        Args:
          self:
          context:
        Returns:
        """
        material = bpy.context.object.active_material
        if not material:
            self.report({"WARNING"}, "No valid material selected")
            return {"CANCELLED"}
        if not hasattr(material, "node_tree"):
            self.report({"WARNING"}, "No node tree found")
            return {"CANCELLED"}
        bpy.ops.object.node_runner_import("INVOKE_DEFAULT")
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
def menu_func_node_runner_import(self, context):
    """
    Args:
      self:
      context:
    Returns:
    """
    self.layout.operator(
        NodeRunnerImportContextMenu.bl_idname, text="Node Runner Import"
    )
