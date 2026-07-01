# ---------------------------------------------------------------------------
# Hierarquia de erros da camada Playwright
#
# PlaywrightAutomationError          <- raiz de todos os erros RPA
#   UIChangedError                   <- seletores nao casaram; UI do Playground mudou
#   PlaygroundLoginRequired          <- sessao expirou ou login necessario
#   PlaygroundLoginTimeout           <- usuario nao completou login manual no tempo
#   PlaygroundConfigurationError     <- URL/configuracao invalida
#   WorkspaceNotFound                <- workspace nao encontrado ou area nao carregou
#   StatusTimeout                    <- monitoramento de status esgotou o tempo
#   UserNotFound                     <- usuario nao encontrado ao adicionar
#   UnsupportedFormat                <- extensao/formato nao suportado pelo Playground
#   ManualReviewRequired             <- arquivo necessita revisao manual
#   UploadFailed                     <- falha geral de upload
#     RecoverableUploadUiError       <- falha de UI recuperavel (reload/reopen)
# ---------------------------------------------------------------------------


class PlaywrightAutomationError(RuntimeError):
    pass


class UIChangedError(PlaywrightAutomationError):
    """Raised when expected UI elements are not found.

    Signals that the Playground interface may have changed (new labels,
    restructured DOM, new layout). Different from a timeout — this means
    "we don't know what to interact with, not that the page was slow."
    """


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
