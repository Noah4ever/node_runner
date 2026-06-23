"""Node data tables for Node Runner.

Provides default values, socket names, and property defaults for Blender
shader, geometry, and compositor nodes.  When running inside Blender, call ``refresh()`` at addon
registration to build tables from the live node system. This means the
addon automatically adapts when Blender adds or changes node sockets.

Static fallback tables (Blender 4.5) are used outside Blender (e.g. in
tests or standalone tools).
"""

from .constants import EXCLUDE_NODE_PROPS

# Common node properties (not node-type-specific)
# Filtered out when reading node-type-specific property defaults.
_COMMON_NODE_PROPS = frozenset(
    {
        "color",
        "height",
        "hide",
        "internal_links",
        "is_active_output",
        "label",
        "location",
        "mute",
        "name",
        "parent",
        "select",
        "show_options",
        "show_preview",
        "show_texture",
        "target",
        "type",
        "use_custom_color",
        "width",
        "width_hidden",
    }
)


# Static fallback tables (Blender 4.5)
#
# Maps node bl_idname to dict with optional "inputs" and "props" keys.
#   "inputs": list of default socket values (positional)
#   "props":  dict of property name to default value
#
# These are used when bpy is not available (tests, external tools).
# When running inside Blender, refresh() replaces them with live data.

_FALLBACK_DEFAULTS = {
    # Shader nodes
    "ShaderNodeBsdfPrincipled": {
        "inputs": [
            [0.8, 0.8, 0.8, 1.0],  # Base Color
            0.0,  # Metallic
            0.5,  # Roughness
            1.45,  # IOR
            0.0,  # Alpha
            [1.0, 1.0, 1.0, 1.0],  # Subsurface Color
            0.0,  # Diffuse Roughness
            [0.0, 0.0, 0.0, 1.0],  # Subsurface Color2
            0.0,  # Subsurface Weight
            [0.0, 0.0, 0.0],  # Subsurface Radius
            0.0,  # Subsurface Scale
            0.0,  # Subsurface IOR
            0.0,  # Subsurface Anisotropy
            0.5,  # Specular IOR Level
            [1.0, 1.0, 1.0, 1.0],  # Specular Tint
            0.0,  # Anisotropic
            0.0,  # Anisotropic Rotation
            [0.0, 0.0, 0.0],  # Tangent
            0.0,  # Transmission Weight
            0.0,  # Coat Weight
            0.03,  # Coat Roughness
            1.5,  # Coat IOR
            [1.0, 1.0, 1.0, 1.0],  # Coat Tint
            [0.0, 0.0, 0.0],  # Coat Normal
            0.0,  # Sheen Weight
            0.5,  # Sheen Roughness
            [1.0, 1.0, 1.0, 1.0],  # Sheen Tint
            [1.0, 1.0, 1.0, 1.0],  # Emission Color
            0.0,  # Emission Strength
            0.0,  # Thin Film Thickness
            1.33,  # Thin Film IOR
        ],
        "props": {
            "distribution": "MULTI_GGX",
            "subsurface_method": "RANDOM_WALK",
        },
    },
    "ShaderNodeBsdfGlass": {
        "inputs": [
            [1.0, 1.0, 1.0, 1.0],  # Color
            0.0,  # Roughness
            1.45,  # IOR
            [0.0, 0.0, 0.0],  # Normal
            0.0,  # Weight
        ],
        "props": {"distribution": "MULTI_GGX"},
    },
    "ShaderNodeBsdfAnisotropic": {
        "inputs": [
            [0.8, 0.8, 0.8, 1.0],  # Color
            0.5,  # Roughness
            0.0,  # Anisotropy
            0.0,  # Rotation
            [0.0, 0.0, 0.0],  # Normal
            [0.0, 0.0, 0.0],  # Tangent
            0.0,  # Weight
        ],
        "props": {"distribution": "MULTI_GGX"},
    },
    "ShaderNodeBsdfGlossy": {
        "inputs": [
            [0.8, 0.8, 0.8, 1.0],  # Color
            0.5,  # Roughness
            [0.0, 0.0, 0.0],  # Normal
            0.0,  # Weight
        ],
        "props": {"distribution": "MULTI_GGX"},
    },
    "ShaderNodeBsdfRefraction": {
        "inputs": [
            [1.0, 1.0, 1.0, 1.0],  # Color
            0.0,  # Roughness
            1.45,  # IOR
            [0.0, 0.0, 0.0],  # Normal
            0.0,  # Weight
        ],
        "props": {"distribution": "BECKMANN"},
    },
    "ShaderNodeEmission": {
        "inputs": [
            [1.0, 1.0, 1.0, 1.0],  # Color
            1.0,  # Strength
            0.0,  # Weight
        ],
    },
    "ShaderNodeMixShader": {
        "inputs": [0.5, None, None],
    },
    "ShaderNodeOutputMaterial": {
        "inputs": [None, None, [0.0, 0.0, 0.0], 0.0],
        "props": {"is_active_output": True, "target": "ALL"},
    },
    "ShaderNodeOutputWorld": {
        "inputs": [None, None, [0.0, 0.0, 0.0], 0.0],
        "props": {"is_active_output": True, "target": "ALL"},
    },
    # Texture nodes
    "ShaderNodeTexNoise": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            0.0,  # W
            5.0,  # Scale
            2.0,  # Detail
            0.5,  # Roughness
            2.0,  # Lacunarity
            0.0,  # Distortion
            0.0,  # Min
            1.0,  # Max
            1.0,  # Randomness
        ],
        "props": {
            "noise_dimensions": "3D",
            "noise_type": "FBM",
            "normalize": True,
        },
    },
    "ShaderNodeTexVoronoi": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            0.0,  # W
            5.0,  # Scale
            0.5,  # Smoothness
            1.0,  # Exponent
            0.5,  # Randomness
        ],
        "props": {
            "voronoi_dimensions": "3D",
            "feature": "F1",
            "distance": "EUCLIDEAN",
            "normalize": False,
        },
    },
    "ShaderNodeTexMusgrave": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            0.0,  # W
            5.0,  # Scale
            2.0,  # Detail
            2.0,  # Dimension
            2.0,  # Lacunarity
            0.0,  # Offset
            1.0,  # Gain
        ],
        "props": {
            "musgrave_dimensions": "3D",
            "musgrave_type": "FBM",
        },
    },
    "ShaderNodeTexWave": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            5.0,  # Scale
            0.0,  # Distortion
            2.0,  # Detail
            1.0,  # Detail Scale
            0.5,  # Detail Roughness
            0.5,  # Phase Offset
        ],
        "props": {
            "wave_type": "BANDS",
            "bands_direction": "X",
            "rings_direction": "X",
            "wave_profile": "SIN",
        },
    },
    "ShaderNodeTexGradient": {
        "inputs": [[0.0, 0.0, 0.0]],
        "props": {"gradient_type": "LINEAR"},
    },
    "ShaderNodeTexChecker": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            [0.8, 0.8, 0.8, 1.0],  # Color1
            [0.2, 0.2, 0.2, 1.0],  # Color2
            5.0,  # Scale
        ],
    },
    "ShaderNodeTexBrick": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            [0.8, 0.8, 0.8, 1.0],  # Color1
            [0.2, 0.2, 0.2, 1.0],  # Color2
            [0.0, 0.0, 0.0, 1.0],  # Mortar
            5.0,  # Scale
            0.02,  # Mortar Size
            0.1,  # Mortar Smooth
            1.0,  # Bias
            0.5,  # Brick Width
            0.25,  # Row Height
        ],
    },
    "ShaderNodeTexImage": {
        "inputs": [[0.0, 0.0, 0.0]],
        "props": {
            "projection": "FLAT",
            "interpolation": "Linear",
            "projection_blend": 0.0,
            "extension": "REPEAT",
        },
    },
    "ShaderNodeTexEnvironment": {
        "inputs": [[0.0, 0.0, 0.0]],
        "props": {
            "projection": "EQUIRECTANGULAR",
            "interpolation": "Linear",
        },
    },
    # Color / converter nodes
    "ShaderNodeMixRGB": {
        "inputs": [
            0.5,  # Fac
            [0.5, 0.5, 0.5, 1.0],  # Color1
            [0.5, 0.5, 0.5, 1.0],  # Color2
        ],
        "props": {"blend_type": "MIX", "use_alpha": False, "use_clamp": False},
    },
    "ShaderNodeMix": {
        "inputs": [
            0.5,  # Factor (float)
            [0.5, 0.5, 0.5],  # Factor (vector)
            0.0,  # A (float)
            0.0,  # B (float)
            [0.5, 0.5, 0.5, 1.0],  # A (color)
            [0.5, 0.5, 0.5, 1.0],  # B (color)
            [0.0, 0.0, 0.0],  # A (vector)
            [0.0, 0.0, 0.0],  # B (vector)
            [0.0, 0.0, 0.0, 1.0],  # A (rotation)
            [0.0, 0.0, 0.0, 1.0],  # B (rotation)
        ],
        "props": {
            "data_type": "FLOAT",
            "blend_type": "MIX",
            "clamp_factor": True,
            "clamp_result": False,
            "factor_mode": "UNIFORM",
        },
    },
    "ShaderNodeMapRange": {
        "inputs": [
            1.0,  # Value
            0.0,  # From Min
            1.0,  # From Max
            0.0,  # To Min
            1.0,  # To Max
            4.0,  # Steps
            [0.0, 0.0, 0.0],  # Vector
            [0.0, 0.0, 0.0],  # From Min (vec)
            [1.0, 1.0, 1.0],  # From Max (vec)
            [0.0, 0.0, 0.0],  # To Min (vec)
            [1.0, 1.0, 1.0],  # To Max (vec)
            [4.0, 4.0, 4.0],  # Steps (vec)
        ],
        "props": {
            "data_type": "FLOAT",
            "interpolation_type": "LINEAR",
            "clamp": True,
        },
    },
    "ShaderNodeMath": {
        "inputs": [0.5, 0.5, 0.5],
        "props": {"operation": "ADD", "use_clamp": False},
    },
    "ShaderNodeVectorMath": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector A
            [0.0, 0.0, 0.0],  # Vector B
            [0.0, 0.0, 0.0],  # Vector C
            1.0,  # Scale
        ],
        "props": {"operation": "ADD"},
    },
    "ShaderNodeValToRGB": {
        "inputs": [0.5],
    },
    "ShaderNodeInvert": {
        "inputs": [1.0, [1.0, 1.0, 1.0, 1.0]],
    },
    "ShaderNodeHueSaturation": {
        "inputs": [
            0.5,  # Hue
            1.0,  # Saturation
            1.0,  # Value
            1.0,  # Fac
            [0.8, 0.8, 0.8, 1.0],  # Color
        ],
    },
    "ShaderNodeBrightContrast": {
        "inputs": [[1.0, 1.0, 1.0, 1.0], 0.0, 0.0],
    },
    "ShaderNodeGamma": {
        "inputs": [[1.0, 1.0, 1.0, 1.0], 1.0],
    },
    "ShaderNodeRGBCurve": {
        "inputs": [1.0, [1.0, 1.0, 1.0, 1.0]],
    },
    # Vector nodes
    "ShaderNodeMapping": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            [0.0, 0.0, 0.0],  # Location
            [0.0, 0.0, 0.0],  # Rotation
            [1.0, 1.0, 1.0],  # Scale
        ],
        "props": {"vector_type": "POINT"},
    },
    "ShaderNodeBump": {
        "inputs": [
            1.0,  # Strength
            1.0,  # Distance
            0.5,  # Height
            1.0,  # Height_dx
            [0.0, 0.0, 0.0],  # Normal
        ],
        "props": {"invert": False},
    },
    "ShaderNodeNormalMap": {
        "inputs": [1.0, [0.5, 0.5, 1.0, 1.0]],
        "props": {"space": "TANGENT", "uv_map": ""},
    },
    "ShaderNodeDisplacement": {
        "inputs": [0.0, 1.0, 0.5, [0.0, 0.0, 0.0]],
        "props": {"space": "OBJECT"},
    },
    "ShaderNodeVectorRotate": {
        "inputs": [
            [0.0, 0.0, 0.0],  # Vector
            [0.0, 0.0, 1.0],  # Center
            [0.0, 0.0, 1.0],  # Axis
            0.0,  # Angle
            [0.0, 0.0, 0.0],  # Rotation
        ],
        "props": {"rotation_type": "AXIS_ANGLE", "invert": False},
    },
    # Input nodes
    "ShaderNodeTexCoord": {
        "props": {"from_instancer": False},
    },
    "ShaderNodeLayerWeight": {
        "inputs": [0.5, [0.0, 0.0, 0.0]],
    },
    "ShaderNodeFresnel": {
        "inputs": [1.45, [0.0, 0.0, 0.0]],
    },
    "ShaderNodeValue": {
        "inputs": [],
    },
    "ShaderNodeRGB": {
        "inputs": [],
    },
    "ShaderNodeSeparateXYZ": {
        "inputs": [[0.0, 0.0, 0.0]],
    },
    "ShaderNodeCombineXYZ": {
        "inputs": [0.0, 0.0, 0.0],
    },
    "ShaderNodeSeparateColor": {
        "inputs": [[0.8, 0.8, 0.8, 1.0]],
        "props": {"mode": "RGB"},
    },
    "ShaderNodeCombineColor": {
        "inputs": [0.0, 0.0, 0.0, 1.0],
        "props": {"mode": "RGB"},
    },
    "ShaderNodeClamp": {
        "inputs": [1.0, 0.0, 1.0],
        "props": {"clamp_type": "MINMAX"},
    },
}

# Socket name tables
#
# Maps node bl_idname to list of socket names (positional).

_FALLBACK_INPUT_NAMES = {
    "ShaderNodeBsdfPrincipled": [
        "Base Color",
        "Metallic",
        "Roughness",
        "IOR",
        "Alpha",
        "Subsurface Color",
        "Diffuse Roughness",
        "Subsurface Color2",
        "Subsurface Weight",
        "Subsurface Radius",
        "Subsurface Scale",
        "Subsurface IOR",
        "Subsurface Anisotropy",
        "Specular IOR Level",
        "Specular Tint",
        "Anisotropic",
        "Anisotropic Rotation",
        "Tangent",
        "Transmission Weight",
        "Coat Weight",
        "Coat Roughness",
        "Coat IOR",
        "Coat Tint",
        "Coat Normal",
        "Sheen Weight",
        "Sheen Roughness",
        "Sheen Tint",
        "Emission Color",
        "Emission Strength",
        "Thin Film Thickness",
        "Thin Film IOR",
    ],
    "ShaderNodeBsdfGlass": ["Color", "Roughness", "IOR", "Normal", "Weight"],
    "ShaderNodeBsdfAnisotropic": [
        "Color",
        "Roughness",
        "Anisotropy",
        "Rotation",
        "Normal",
        "Tangent",
        "Weight",
    ],
    "ShaderNodeBsdfGlossy": ["Color", "Roughness", "Normal", "Weight"],
    "ShaderNodeBsdfRefraction": ["Color", "Roughness", "IOR", "Normal", "Weight"],
    "ShaderNodeEmission": ["Color", "Strength", "Weight"],
    "ShaderNodeMixShader": ["Fac", "Shader", "Shader"],
    "ShaderNodeOutputMaterial": ["Surface", "Volume", "Displacement", "Thickness"],
    "ShaderNodeOutputWorld": ["Surface", "Volume", "Displacement", "Thickness"],
    "ShaderNodeTexNoise": [
        "Vector",
        "W",
        "Scale",
        "Detail",
        "Roughness",
        "Lacunarity",
        "Distortion",
        "Min",
        "Max",
        "Randomness",
    ],
    "ShaderNodeTexVoronoi": [
        "Vector",
        "W",
        "Scale",
        "Smoothness",
        "Exponent",
        "Randomness",
    ],
    "ShaderNodeTexMusgrave": [
        "Vector",
        "W",
        "Scale",
        "Detail",
        "Dimension",
        "Lacunarity",
        "Offset",
        "Gain",
    ],
    "ShaderNodeTexWave": [
        "Vector",
        "Scale",
        "Distortion",
        "Detail",
        "Detail Scale",
        "Detail Roughness",
        "Phase Offset",
    ],
    "ShaderNodeTexGradient": ["Vector"],
    "ShaderNodeTexChecker": ["Vector", "Color1", "Color2", "Scale"],
    "ShaderNodeTexBrick": [
        "Vector",
        "Color1",
        "Color2",
        "Mortar",
        "Scale",
        "Mortar Size",
        "Mortar Smooth",
        "Bias",
        "Brick Width",
        "Row Height",
    ],
    "ShaderNodeTexImage": ["Vector"],
    "ShaderNodeTexEnvironment": ["Vector"],
    "ShaderNodeMixRGB": ["Fac", "Color1", "Color2"],
    "ShaderNodeMix": [
        "Factor (float)",
        "Factor (vector)",
        "A (float)",
        "B (float)",
        "A (color)",
        "B (color)",
        "A (vector)",
        "B (vector)",
        "A (rotation)",
        "B (rotation)",
    ],
    "ShaderNodeMapRange": [
        "Value",
        "From Min",
        "From Max",
        "To Min",
        "To Max",
        "Steps",
        "Vector",
        "From Min (vec)",
        "From Max (vec)",
        "To Min (vec)",
        "To Max (vec)",
        "Steps (vec)",
    ],
    "ShaderNodeMath": ["Value", "Value", "Value"],
    "ShaderNodeVectorMath": ["Vector A", "Vector B", "Vector C", "Scale"],
    "ShaderNodeValToRGB": ["Fac"],
    "ShaderNodeInvert": ["Fac", "Color"],
    "ShaderNodeHueSaturation": ["Hue", "Saturation", "Value", "Fac", "Color"],
    "ShaderNodeBrightContrast": ["Color", "Bright", "Contrast"],
    "ShaderNodeGamma": ["Color", "Gamma"],
    "ShaderNodeRGBCurve": ["Fac", "Color"],
    "ShaderNodeMapping": ["Vector", "Location", "Rotation", "Scale"],
    "ShaderNodeBump": ["Strength", "Distance", "Height", "Height_dx", "Normal"],
    "ShaderNodeNormalMap": ["Strength", "Color"],
    "ShaderNodeDisplacement": ["Height", "Midlevel", "Scale", "Normal"],
    "ShaderNodeVectorRotate": ["Vector", "Center", "Axis", "Angle", "Rotation"],
    "ShaderNodeLayerWeight": ["Blend", "Normal"],
    "ShaderNodeFresnel": ["IOR", "Normal"],
    "ShaderNodeSeparateXYZ": ["Vector"],
    "ShaderNodeCombineXYZ": ["X", "Y", "Z"],
    "ShaderNodeSeparateColor": ["Color"],
    "ShaderNodeCombineColor": ["Red", "Green", "Blue", "Alpha"],
    "ShaderNodeClamp": ["Value", "Min", "Max"],
}

_FALLBACK_OUTPUT_NAMES = {
    "ShaderNodeTexNoise": ["Fac", "Color"],
    "ShaderNodeTexVoronoi": ["Distance", "Color", "Position", "W"],
    "ShaderNodeTexMusgrave": ["Height"],
    "ShaderNodeTexWave": ["Color", "Fac"],
    "ShaderNodeTexGradient": ["Color", "Fac"],
    "ShaderNodeTexChecker": ["Color", "Fac"],
    "ShaderNodeTexBrick": ["Color", "Fac"],
    "ShaderNodeTexImage": ["Color", "Alpha"],
    "ShaderNodeTexEnvironment": ["Color"],
    "ShaderNodeMixRGB": ["Color"],
    "ShaderNodeMix": [
        "Result (float)",
        "Result (color)",
        "Result (vector)",
        "Result (rotation)",
    ],
    "ShaderNodeMath": ["Value"],
    "ShaderNodeVectorMath": ["Vector", "Value"],
    "ShaderNodeMapRange": ["Result", "Vector"],
    "ShaderNodeValToRGB": ["Color", "Alpha"],
    "ShaderNodeInvert": ["Color"],
    "ShaderNodeHueSaturation": ["Color"],
    "ShaderNodeBrightContrast": ["Color"],
    "ShaderNodeGamma": ["Color"],
    "ShaderNodeRGBCurve": ["Color"],
    "ShaderNodeMapping": ["Vector"],
    "ShaderNodeBump": ["Normal"],
    "ShaderNodeNormalMap": ["Normal"],
    "ShaderNodeDisplacement": ["Displacement"],
    "ShaderNodeVectorRotate": ["Vector"],
    "ShaderNodeTexCoord": [
        "Generated",
        "Normal",
        "UV",
        "Object",
        "Camera",
        "Window",
        "Reflection",
    ],
    "ShaderNodeLayerWeight": ["Fresnel", "Facing"],
    "ShaderNodeFresnel": ["Fac"],
    "ShaderNodeValue": ["Value"],
    "ShaderNodeRGB": ["Color"],
    "ShaderNodeSeparateXYZ": ["X", "Y", "Z"],
    "ShaderNodeCombineXYZ": ["Vector"],
    "ShaderNodeSeparateColor": ["Red", "Green", "Blue", "Alpha"],
    "ShaderNodeCombineColor": ["Color"],
    "ShaderNodeClamp": ["Result"],
    "ShaderNodeBsdfPrincipled": ["BSDF"],
    "ShaderNodeBsdfGlass": ["BSDF"],
    "ShaderNodeBsdfAnisotropic": ["BSDF"],
    "ShaderNodeBsdfGlossy": ["BSDF"],
    "ShaderNodeBsdfRefraction": ["BSDF"],
    "ShaderNodeEmission": ["Emission"],
    "ShaderNodeMixShader": ["Shader"],
}


# Module-level data (updated in place by refresh())

NODE_DEFAULTS = dict(_FALLBACK_DEFAULTS)
INPUT_NAMES = dict(_FALLBACK_INPUT_NAMES)
OUTPUT_NAMES = dict(_FALLBACK_OUTPUT_NAMES)


def _introspect_tree(bpy, tree, prefix):
    """Walk ``bpy.types`` for node classes whose name starts with *prefix*,
    instantiate each in *tree*, and read default input values, socket
    names, and property defaults.

    Returns ``(defaults, input_names, output_names)`` dicts keyed by
    ``bl_idname``.
    """
    skip = EXCLUDE_NODE_PROPS | _COMMON_NODE_PROPS

    node_types = sorted(
        name
        for name in dir(bpy.types)
        if name.startswith(prefix) and name != prefix
    )

    defaults = {}
    input_names = {}
    output_names = {}

    for ntype in node_types:
        try:
            node = tree.nodes.new(ntype)
        except (RuntimeError, ValueError):
            continue

        in_defaults = []
        in_names = []
        for inp in node.inputs:
            in_names.append(inp.name)
            if hasattr(inp, "default_value"):
                v = inp.default_value
                if isinstance(v, str):
                    in_defaults.append(v)
                elif isinstance(v, float):
                    in_defaults.append(round(v, 6))
                elif isinstance(v, (int, bool)):
                    in_defaults.append(v)
                elif hasattr(v, "__len__"):
                    try:
                        in_defaults.append([round(float(x), 6) for x in v])
                    except (TypeError, ValueError):
                        in_defaults.append(None)
                else:
                    in_defaults.append(v)
            else:
                in_defaults.append(None)

        out_names = [o.name for o in node.outputs]

        props = {}
        for prop in node.bl_rna.properties:
            key = prop.identifier
            if key in skip or prop.is_readonly:
                continue
            if prop.type in ("POINTER", "COLLECTION"):
                continue
            try:
                val = getattr(node, key)
                if isinstance(val, bool):
                    props[key] = val
                elif isinstance(val, str):
                    props[key] = val
                elif isinstance(val, (int, float)):
                    props[key] = val
                elif hasattr(val, "__len__"):
                    props[key] = list(val)
            except (TypeError, ValueError, AttributeError, RuntimeError):
                continue

        entry = {}
        if in_defaults:
            entry["inputs"] = in_defaults
        if props:
            entry["props"] = props

        defaults[ntype] = entry
        if in_names:
            input_names[ntype] = in_names
        if out_names:
            output_names[ntype] = out_names

        try:
            tree.nodes.remove(node)
        except (RuntimeError, ReferenceError):
            # Some zone-paired nodes auto-remove their partner; ignore.
            pass

    return defaults, input_names, output_names


def refresh():
    """Query Blender for current node defaults.

    Call this at addon registration.  Discovers all ShaderNode, GeometryNode, and
    CompositorNode types, creates temporary instances, and reads their
    default input values, socket names, and property defaults.  The
    module-level dicts ``NODE_DEFAULTS``, ``INPUT_NAMES``, and
    ``OUTPUT_NAMES`` are updated in place so existing imports see the
    fresh data.
    """
    try:
        import bpy
    except ImportError:
        return

    new_defaults = {}
    new_input_names = {}
    new_output_names = {}

    # Shader nodes — instantiated inside a temporary material's node tree.
    mat = None
    try:
        mat = bpy.data.materials.new("_nr_tmp_shader")
    except (RuntimeError, AttributeError):
        mat = None

    if mat is not None:
        try:
            mat.use_nodes = True
            tree = mat.node_tree
            for n in list(tree.nodes):
                tree.nodes.remove(n)
            d, i, o = _introspect_tree(bpy, tree, "ShaderNode")
            new_defaults.update(d)
            new_input_names.update(i)
            new_output_names.update(o)
        finally:
            try:
                bpy.data.materials.remove(mat)
            except (RuntimeError, AttributeError):
                pass

    # Geometry nodes — instantiated inside a temporary GeometryNodeTree.
    gn_tree = None
    try:
        gn_tree = bpy.data.node_groups.new("_nr_tmp_gn", "GeometryNodeTree")
    except (RuntimeError, AttributeError, TypeError):
        gn_tree = None

    if gn_tree is not None:
        try:
            for n in list(gn_tree.nodes):
                gn_tree.nodes.remove(n)
            d, i, o = _introspect_tree(bpy, gn_tree, "GeometryNode")
            new_defaults.update(d)
            new_input_names.update(i)
            new_output_names.update(o)
        finally:
            try:
                bpy.data.node_groups.remove(gn_tree)
            except (RuntimeError, AttributeError):
                pass

    # Compositor nodes — instantiated in a temporary scene compositor tree.
    scene = None
    old_scene = None
    try:
        old_scene = getattr(bpy.context.window, "scene", None) if getattr(bpy.context, "window", None) else None
        scene = bpy.data.scenes.new("_nr_tmp_compositor")
        if getattr(bpy.context, "window", None) is not None:
            bpy.context.window.scene = scene
        scene.use_nodes = True
        tree = scene.node_tree
        for n in list(tree.nodes):
            tree.nodes.remove(n)
        d, i, o = _introspect_tree(bpy, tree, "CompositorNode")
        new_defaults.update(d)
        new_input_names.update(i)
        new_output_names.update(o)
    except (RuntimeError, AttributeError, TypeError):
        pass
    finally:
        try:
            if old_scene is not None and getattr(bpy.context, "window", None) is not None:
                bpy.context.window.scene = old_scene
        except (RuntimeError, AttributeError):
            pass
        if scene is not None:
            try:
                bpy.data.scenes.remove(scene)
            except (RuntimeError, AttributeError):
                pass

    if not new_defaults:
        return  # Query produced nothing, keep fallback tables

    # Update in place so existing imports see changes
    NODE_DEFAULTS.clear()
    NODE_DEFAULTS.update(new_defaults)
    INPUT_NAMES.clear()
    INPUT_NAMES.update(new_input_names)
    OUTPUT_NAMES.clear()
    OUTPUT_NAMES.update(new_output_names)
