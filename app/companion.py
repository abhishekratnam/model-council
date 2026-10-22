"""Backwards-compatible development entry point for the companion package."""
import sys

from app.core.exceptions import CouncilError
from model_council_companion import server

server.CouncilError = CouncilError
if __name__ == "__main__":
    server.main()
else:
    sys.modules[__name__] = server
