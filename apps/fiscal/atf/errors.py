from typing import Any


class AtfError(Exception):
    safe_code = "atf_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_code)


class AtfAuthenticationError(AtfError):
    safe_code = "atf_authentication_failed"


class AtfSessionExpired(AtfAuthenticationError):
    safe_code = "atf_session_expired"


class AtfPermissionError(AtfError):
    safe_code = "atf_permission_denied"


class AtfPortalChanged(AtfError):
    safe_code = "atf_portal_changed"


class AtfTransientError(AtfError):
    safe_code = "atf_transient_error"

    def __init__(self, message: Any = None, *, retry_after_seconds: Any = 0) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(0, retry_after_seconds)


class AtfSubmissionUncertain(AtfError):
    safe_code = "atf_submission_uncertain"


class AtfAmbiguousResult(AtfError):
    safe_code = "atf_result_ambiguous"


class AtfArtifactError(AtfError):
    safe_code = "atf_artifact_rejected"


class AtfIdentityMismatch(AtfError):
    safe_code = "atf_identity_mismatch"
