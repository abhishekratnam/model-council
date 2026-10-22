"""Runtime defaults shared by the standalone package and the web app."""
from types import SimpleNamespace


class CompanionError(Exception):
    """Safe validation and workspace error for standalone companion use."""


CouncilError = CompanionError


settings = SimpleNamespace(MODEL_COUNCIL_WORKSPACE_ROOT="")

WORKSPACE_MAX_TREE_ENTRIES = 400
WORKSPACE_MAX_TREE_DEPTH = 8
WORKSPACE_MAX_FILE_BYTES = 120_000
WORKSPACE_MAX_READ_LINES = 1_200
WORKSPACE_SEARCH_MAX_RESULTS = 40
WORKSPACE_COMMAND_TIMEOUT_SECONDS = 60
WORKSPACE_COMMAND_OUTPUT_CHARS = 4_000
WORKSPACE_SERVER_START_TIMEOUT_SECONDS = 20
CODE_AGENT_SESSION_LOG_PATH = ".model_council/plans/last_session.md"
CODE_AGENT_SESSION_LOG_MAX_CHARS = 12_000
