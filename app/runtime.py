"""Per-application vault state; shared across this app's routers, not apps."""

from dataclasses import dataclass, field

from .vault import UnlockAttemptLimiter, VaultSessions


VAULT_COOKIE_NAME = "projmemo_vault"


@dataclass
class AppRuntime:
    vault_sessions: VaultSessions = field(default_factory=VaultSessions)
    unlock_attempt_limiter: UnlockAttemptLimiter = field(default_factory=UnlockAttemptLimiter)


def get_runtime(request) -> AppRuntime:
    return request.app.state.runtime
