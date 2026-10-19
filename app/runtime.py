"""Per-application vault state; shared across this app's routers, not apps."""

from dataclasses import dataclass, field

from .vault import UnlockAttemptLimiter, VaultSessions
from .submissions import SubmissionRegistry
from .backup_plans import BackupPlans


VAULT_COOKIE_NAME = "projmemo_vault"


@dataclass
class AppRuntime:
    submissions: SubmissionRegistry = field(default_factory=SubmissionRegistry)
    vault_sessions: VaultSessions = field(default_factory=VaultSessions)
    unlock_attempt_limiter: UnlockAttemptLimiter = field(default_factory=UnlockAttemptLimiter)
    backup_plans: BackupPlans = field(default_factory=BackupPlans)


def get_runtime(request) -> AppRuntime:
    return request.app.state.runtime
