"""Safe manifest-only plugin loader boundary.

Batch 1 intentionally validates manifests and registers metadata only. It does not import or
execute third-party plugin code.
"""

from backend.app.plugins.service import PluginLoadRequest, plugin_service

__all__ = ["PluginLoadRequest", "plugin_service"]
