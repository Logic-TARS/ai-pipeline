class PipelineError(Exception):
    """Base class for expected pipeline failures."""


class ConfigError(PipelineError):
    """Configuration is missing or invalid."""


class ExternalToolError(PipelineError):
    """An external tool failed."""


class MediaValidationError(PipelineError):
    """A generated media artifact is missing, corrupt, or does not match its profile."""


class PrivateVisibilityUnsupportedError(PipelineError):
    """The uploader cannot guarantee private visibility."""


class UnknownContentTypeError(PipelineError):
    """The router could not map a task to a supported content type."""
