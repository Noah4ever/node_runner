"""
Addon preferences for Node Runner, including the library repository list.

Kept apart from :mod:`operators` so the repository PropertyGroup can be
registered before anything that references it, and so the operators module
does not grow a second subsystem.
"""

import bpy

from . import library



class NODE_RUNNER_RepoItem(bpy.types.PropertyGroup):
    """One node library repository configured by the user."""

    name: bpy.props.StringProperty(
        name="Name",
        default="New Repository",
        description="Label shown in the library panel",
    )  # type: ignore
    url: bpy.props.StringProperty(
        name="URL",
        description=(
            "Repository holding config.json. Accepts a GitHub page URL, a raw "
            "URL, owner/repo shorthand, or a local folder path"
        ),
    )  # type: ignore
    branch: bpy.props.StringProperty(
        name="Branch",
        default="main",
        description=(
            "Branch or tag to read from. Ignored when the URL already names one"
        ),
    )  # type: ignore
    token: bpy.props.StringProperty(
        name="Token",
        subtype="PASSWORD",
        description=(
            "Access token for a private repository. Blender stores addon "
            "preferences unencrypted, so this is kept in plain text on disk"
        ),
    )  # type: ignore
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        default=True,
        description="Include this repository in the library panel",
    )  # type: ignore


class NODE_RUNNER_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    repos: bpy.props.CollectionProperty(
        type=NODE_RUNNER_RepoItem,
        name="Repositories",
    )  # type: ignore

    publish_dir: bpy.props.StringProperty(
        name="Library Folder",
        subtype="DIR_PATH",
        description="Folder Publish to Library last wrote to",
    )  # type: ignore

    def draw(self, context):
        layout = self.layout

        header = layout.row(align=True)
        header.label(text="Library Repositories", icon="URL")
        header.operator("node_runner.repo_add", text="", icon="ADD")
        header.operator("node_runner.library_refresh", text="", icon="FILE_REFRESH")
        header.operator("node_runner.library_clear_cache", text="", icon="TRASH")

        if not self.repos:
            box = layout.box()
            box.label(text="No repositories yet - press + to add one", icon="INFO")
            return

        for index, repo in enumerate(self.repos):
            self._draw_repo(layout, index, repo)

    def _draw_repo(self, layout, index, repo):
        box = layout.box()

        header = box.row(align=True)
        header.prop(repo, "enabled", text="")
        header.prop(repo, "name", text="")
        header.operator(
            "node_runner.repo_remove", text="", icon="X"
        ).index = index

        column = box.column()
        column.use_property_split = True
        column.use_property_decorate = False
        column.prop(repo, "url")
        column.prop(repo, "branch")
        column.prop(repo, "token")

        # Show what the URL actually resolved to - the whole point of
        # accepting several input forms is that mistakes stay visible.
        base, _kind, error = library.normalize_repo_url(repo.url, repo.branch)
        info = box.row()
        info.scale_y = 0.7
        if error:
            info.alert = True
            info.label(text=error, icon="ERROR")
        else:
            info.label(text=base, icon="CHECKMARK")


class NODE_RUNNER_OT_repo_add(bpy.types.Operator):
    """Add a node library repository"""

    bl_idname = "node_runner.repo_add"
    bl_label = "Add Repository"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            self.report({"ERROR"}, "Addon preferences are unavailable")
            return {"CANCELLED"}
        prefs.repos.add()
        return {"FINISHED"}


class NODE_RUNNER_OT_repo_remove(bpy.types.Operator):
    """Remove this node library repository"""

    bl_idname = "node_runner.repo_remove"
    bl_label = "Remove Repository"
    bl_options = {"INTERNAL"}

    index: bpy.props.IntProperty(default=-1)  # type: ignore

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None or not 0 <= self.index < len(prefs.repos):
            self.report({"ERROR"}, "That repository no longer exists")
            return {"CANCELLED"}
        prefs.repos.remove(self.index)
        return {"FINISHED"}


def get_prefs(context):
    """Return addon preferences, with safe fallback defaults."""
    prefs = context.preferences.addons.get(__package__)
    if prefs:
        return prefs.preferences
    return None


def repo_specs(context):
    """Repository settings as plain dicts, safe to hand to the net module."""
    prefs = get_prefs(context)
    if prefs is None:
        return []
    return [
        {
            "name": repo.name.strip(),
            "url": repo.url.strip(),
            "branch": repo.branch.strip(),
            "token": repo.token.strip(),
            "enabled": bool(repo.enabled),
        }
        for repo in prefs.repos
    ]


CLASSES = (
    # The repo PropertyGroup must be registered before the preferences
    # class whose CollectionProperty references it.
    NODE_RUNNER_RepoItem,
    NODE_RUNNER_preferences,
    NODE_RUNNER_OT_repo_add,
    NODE_RUNNER_OT_repo_remove,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
