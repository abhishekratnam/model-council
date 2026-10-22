"""Compatibility import for the standalone companion workspace engine.

The web application and PyPI companion share one implementation so its path
and command safeguards stay in sync.
"""
import sys
from pathlib import Path

from app.core import config as app_config
from app.core.exceptions import CouncilError
from model_council_companion import runtime
from model_council_companion import workspace as implementation


_CONFIG_NAMES = (
    "WORKSPACE_MAX_TREE_ENTRIES",
    "WORKSPACE_MAX_TREE_DEPTH",
    "WORKSPACE_MAX_FILE_BYTES",
    "WORKSPACE_MAX_READ_LINES",
    "WORKSPACE_SEARCH_MAX_RESULTS",
    "WORKSPACE_COMMAND_TIMEOUT_SECONDS",
    "WORKSPACE_COMMAND_OUTPUT_CHARS",
    "WORKSPACE_SERVER_START_TIMEOUT_SECONDS",
    "CODE_AGENT_SESSION_LOG_PATH",
    "CODE_AGENT_SESSION_LOG_MAX_CHARS",
)

runtime.settings = app_config.settings
runtime.CouncilError = CouncilError
for _name in _CONFIG_NAMES:
    setattr(runtime, _name, getattr(app_config, _name))

# The workspace module may have been imported earlier by app.companion.
implementation.settings = app_config.settings
implementation.CouncilError = CouncilError
implementation._REPO_DIR = Path(__file__).resolve().parents[2]
for _name in _CONFIG_NAMES:
    setattr(implementation, _name, getattr(app_config, _name))

# Preserve module identity for existing callers and tests that patch helpers.
sys.modules[__name__] = implementation
