"""User-facing errors raised by deterministic control-plane operations."""


class XHControlError(Exception):
    """Base error for expected control-plane failures."""


class ConfigurationError(XHControlError):
    """Configuration is missing, malformed, or inconsistent."""


class DatabaseInitializationError(XHControlError):
    """SQLite bootstrap could not be completed."""


class TaskNotFoundError(XHControlError):
    """A requested task does not exist."""


class AttemptNotFoundError(XHControlError):
    """A requested execution attempt does not exist."""


class ArtifactNotFoundError(XHControlError):
    """A requested artifact does not exist."""


class DuplicateRecordError(XHControlError):
    """A persistent record already uses the supplied identifier."""


class InvalidTaskTransitionError(XHControlError):
    """A requested task state transition is not permitted."""


class InvalidGenerationError(XHControlError):
    """An attempt generation is invalid or stale."""


class StateConflictError(XHControlError):
    """Persistent state changed while an operation was in progress."""


class PluginError(XHControlError):
    """Base error for plugin registration and contract execution failures."""


class PluginNotFoundError(PluginError):
    """A requested domain plugin is not registered."""


class PluginRegistrationError(PluginError):
    """A plugin cannot be registered against the supported interface."""


class PluginTaskTypeError(PluginError):
    """A plugin does not accept the requested opaque task type."""


class PluginUnavailableError(PluginError):
    """A plugin adapter is unavailable for contract execution."""


class PluginResultError(PluginError):
    """A plugin returned data that cannot safely finalize its task."""


class ChannelError(XHControlError):
    """Base error for execution-channel probing and selection."""


class ChannelExecutionDeferredError(ChannelError):
    """Real channel execution belongs to a later authorized milestone."""


class NoEligibleChannelError(ChannelError):
    """No configured channel satisfies the current routing policy."""


class BudgetError(XHControlError):
    """Base error for cost authorization and persistence."""


class BudgetStateError(BudgetError):
    """A paid-action approval cannot be represented in the current task state."""


class WorkerError(XHControlError):
    """Base error for worker discovery and selection."""


class NoEligibleWorkerError(WorkerError):
    """No enabled worker satisfies the requested capability set."""


class PermissionPolicyError(XHControlError):
    """A task permission cannot be granted by current policy."""


class PermissionApprovalRequiredError(PermissionPolicyError):
    """The requested permission needs an explicit persisted approval."""
