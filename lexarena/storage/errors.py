"""Storage-layer errors. Messages name roles, stores and IDs, never stored content."""

from __future__ import annotations


class AccessDeniedError(PermissionError):
    """The caller's role (or side) may not perform this operation on this store."""


class SealedError(AccessDeniedError):
    """Ground truth or private data requested before the session's verdict is recorded."""


class CredentialLeakError(RuntimeError):
    """A session process can see a credential that only offline or post-verdict processes may hold."""


class StateTransitionError(RuntimeError):
    """A session state change that the state machine or the caller's role does not allow."""


class NotFoundError(LookupError):
    """No document with this ID."""
