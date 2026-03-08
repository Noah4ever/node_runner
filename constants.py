"""
Constants used across the Node Runner addon.
"""

# Header prefix appended to exported strings (hash format only).
# JSON and XML are exported as valid standalone documents with the
# export name embedded inside the data.
EXPORT_HEADER = "__NR"

# Node properties to exclude from serialization.
# These are read-only, internal, or UI-only properties that
# should never be serialized/deserialized.
EXCLUDE_NODE_PROPS = frozenset(
    {
        # Internal / class-level
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
        # Methods / read-only
        "cache_point_density",
        "calc_point_density",
        "calc_point_density_minmax",
        "dimensions",
        "draw_buttons",
        "draw_buttons_ext",
        "draw_label",
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
        # Debug properties (Blender 4.x+)
        "debug_zone_body_lazy_function_graph",
        "debug_zone_lazy_function_graph",
        # Read-only computed
        "location_absolute",
        "warning_propagation",
    }
)

# Readonly properties that should still be serialized.
# These are readonly pointer properties whose sub-data we need to capture.
SERIALIZE_READONLY_PROPS = frozenset(
    {
        "name",
        "inputs",
        "outputs",
        "color_ramp",
        "mapping",
        "texture_mapping",
        "color_mapping",
        "image",
    }
)

# Properties that are read-only and should be skipped during deserialization
READONLY_DESERIALIZE_PROPS = frozenset(
    {
        "type",
        "image_user",
        "input_order",
        "output_order",
        "location_absolute",
    }
)

# Mapping from specific socket sub-types to base types usable for
# NodeTreeInterface.new_socket(). Order matters: first match wins.
SOCKET_BASE_TYPES = [
    "NodeSocketBool",
    "NodeSocketVector",
    "NodeSocketInt",
    "NodeSocketShader",
    "NodeSocketFloat",
    "NodeSocketColor",
    "NodeSocketString",
    "NodeSocketRotation",
    "NodeSocketImage",
    "NodeSocketObject",
    "NodeSocketCollection",
    "NodeSocketGeometry",
    "NodeSocketMenu",
    "NodeSocketMaterial",
    "NodeSocketTexture",
    "NodeSocketMatrix",
]
