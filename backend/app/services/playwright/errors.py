class PlaywrightAutomationError(RuntimeError):
    pass


class PlaygroundLoginRequired(PlaywrightAutomationError):
    pass


class PlaygroundLoginTimeout(PlaywrightAutomationError):
    pass


class PlaygroundConfigurationError(PlaywrightAutomationError):
    pass


class WorkspaceNotFound(PlaywrightAutomationError):
    pass


class UploadFailed(PlaywrightAutomationError):
    pass


class RecoverableUploadUiError(UploadFailed):
    pass


class StatusTimeout(PlaywrightAutomationError):
    pass


class UserNotFound(PlaywrightAutomationError):
    pass


class UnsupportedFormat(PlaywrightAutomationError):
    pass


class ManualReviewRequired(PlaywrightAutomationError):
    pass
