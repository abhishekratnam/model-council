class CouncilError(Exception):
    """A request validation error that is safe to show in the browser."""

class ProviderError(Exception):
    """A provider failure with an already-sanitized user-facing message."""