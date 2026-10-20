"""Password-derived encryption and short-lived sessions for the local vault."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import os
import secrets
import threading
import time
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id


MASTER_PASSWORD_MIN_LENGTH = 16
MASTER_PASSWORD_MAX_LENGTH = 1024
VAULT_SESSION_TTL_SECONDS = 15 * 60
KDF_MEMORY_COST = 64 * 1024
KDF_ITERATIONS = 1
KDF_LANES = 4
_VERIFIER = b"ProjMemo credential vault verifier v1"
_VERIFIER_AAD = b"ProjMemo:vault-verifier:v1"


class VaultError(ValueError):
    """Base error for vault setup and decryption failures."""


class VaultNotInitialized(VaultError):
    """Raised when an operation requires a configured vault."""


class VaultAlreadyInitialized(VaultError):
    """Raised when a vault is configured more than once."""


class InvalidMasterPassword(VaultError):
    """Raised when the supplied master password cannot unlock the vault."""


class VaultRateLimited(VaultError):
    """Raised when too many unlock attempts have failed recently."""


def validate_master_password(password: str) -> None:
    if len(password) > MASTER_PASSWORD_MAX_LENGTH:
        raise VaultError("主密碼不可超過 1024 個字元")
    if len(password) < MASTER_PASSWORD_MIN_LENGTH:
        raise VaultError(f"主密碼至少需要 {MASTER_PASSWORD_MIN_LENGTH} 個字元")


def validate_vault_metadata(row: Any) -> None:
    """Validate untrusted database values before allocating Argon2 memory."""
    message = "保管庫設定格式錯誤或參數不受支援，請使用完整且相容的備份。"
    try:
        for name, length in (("salt", 16), ("verifier_nonce", 12),
                             ("verifier_ciphertext", len(_VERIFIER) + 16)):
            value = row[name]
            if not isinstance(value, bytes) or len(value) != length:
                raise VaultError(message)
        memory, iterations, lanes = (row[name] for name in
                                    ("kdf_memory_cost", "kdf_iterations", "kdf_lanes"))
        if (any(type(value) is not int for value in (memory, iterations, lanes))
                or not 32 * 1024 <= memory <= 128 * 1024
                or not 1 <= iterations <= 4 or not 1 <= lanes <= 8):
            raise VaultError(message)
    except (KeyError, IndexError, TypeError) as error:
        raise VaultError(message) from error


def _derive_key(password: str, salt: bytes, *, memory_cost: int, iterations: int, lanes: int) -> bytes:
    return Argon2id(
        salt=salt,
        length=32,
        iterations=iterations,
        lanes=lanes,
        memory_cost=memory_cost,
    ).derive(password.encode("utf-8"))


def create_vault(connection: Any, password: str) -> bytes:
    """Create vault metadata and return its key for the initial unlocked session."""
    validate_master_password(password)
    if connection.execute("SELECT 1 FROM vault_config WHERE id = 1").fetchone():
        raise VaultAlreadyInitialized("保管庫已經設定")

    key, values = _new_vault_material(password)
    connection.execute(
        """INSERT INTO vault_config
            (id, salt, verifier_nonce, verifier_ciphertext, kdf_memory_cost, kdf_iterations, kdf_lanes)
           VALUES (1, ?, ?, ?, ?, ?, ?)""", values,
    )
    return key


def _new_vault_material(password: str, *, memory_cost: int = KDF_MEMORY_COST,
                        iterations: int = KDF_ITERATIONS, lanes: int = KDF_LANES) -> tuple[bytes, tuple]:
    salt = os.urandom(16)
    key = _derive_key(
        password,
        salt,
        memory_cost=memory_cost,
        iterations=iterations,
        lanes=lanes,
    )
    verifier_nonce = os.urandom(12)
    verifier_ciphertext = AESGCM(key).encrypt(verifier_nonce, _VERIFIER, _VERIFIER_AAD)
    return key, (salt, verifier_nonce, verifier_ciphertext, memory_cost, iterations, lanes)


def unlock_vault(connection: Any, password: str) -> bytes:
    # Reject excessive input before a database read or Argon2 allocation.
    if len(password) > MASTER_PASSWORD_MAX_LENGTH:
        raise VaultError("主密碼不可超過 1024 個字元")
    row = connection.execute("SELECT * FROM vault_config WHERE id = 1").fetchone()
    if row is None:
        raise VaultNotInitialized("尚未設定密碼保管庫")
    validate_vault_metadata(row)
    key = _derive_key(
        password,
        bytes(row["salt"]),
        memory_cost=int(row["kdf_memory_cost"]),
        iterations=int(row["kdf_iterations"]),
        lanes=int(row["kdf_lanes"]),
    )
    try:
        verifier = AESGCM(key).decrypt(
            bytes(row["verifier_nonce"]),
            bytes(row["verifier_ciphertext"]),
            _VERIFIER_AAD,
        )
    except InvalidTag as error:
        raise InvalidMasterPassword("主密碼錯誤") from error
    if verifier != _VERIFIER:
        raise InvalidMasterPassword("主密碼錯誤")
    return key


def encrypt_secret(key: bytes, project_id: int, account_id: int, secret: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    associated_data = f"ProjMemo:account-secret:v1:{project_id}:{account_id}".encode("ascii")
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), associated_data)
    return ciphertext, nonce


def decrypt_secret(
    key: bytes,
    project_id: int,
    account_id: int,
    ciphertext: bytes,
    nonce: bytes,
) -> str:
    associated_data = f"ProjMemo:account-secret:v1:{project_id}:{account_id}".encode("ascii")
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data)
    except (InvalidTag, ValueError) as error:
        raise VaultError("無法解密此密碼；資料可能已損毀或不屬於此帳號") from error
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VaultError("密碼資料格式錯誤") from error


def reencrypt_vault(connection: Any, old_key: bytes, new_password: str) -> int:
    """Caller owns the one writer transaction; plaintext is held one row at a time."""
    validate_master_password(new_password)
    config = connection.execute("SELECT * FROM vault_config WHERE id = 1").fetchone()
    if config is None:
        raise VaultNotInitialized("尚未設定密碼保管庫")
    validate_vault_metadata(config)
    new_key, values = _new_vault_material(new_password, memory_cost=config["kdf_memory_cost"],
        iterations=config["kdf_iterations"], lanes=config["kdf_lanes"])
    count = 0
    rows = connection.execute(
        "SELECT id, project_id, secret_ciphertext, secret_nonce FROM access_accounts "
        "WHERE secret_ciphertext IS NOT NULL OR secret_nonce IS NOT NULL ORDER BY id")
    for row in rows:
        if row["secret_ciphertext"] is None or row["secret_nonce"] is None:
            raise VaultError("密碼資料格式錯誤")
        secret = decrypt_secret(old_key, row["project_id"], row["id"], row["secret_ciphertext"], row["secret_nonce"])
        try:
            ciphertext, nonce = encrypt_secret(new_key, row["project_id"], row["id"], secret)
            if decrypt_secret(new_key, row["project_id"], row["id"], ciphertext, nonce) != secret:
                raise VaultError("密碼資料格式錯誤")
            connection.execute("UPDATE access_accounts SET secret_ciphertext = ?, secret_nonce = ? WHERE id = ?",
                               (ciphertext, nonce, row["id"]))
        finally:
            # Drop references, not a guarantee of secure memory erasure in Python.
            secret = None
        count += 1
    connection.execute(
        "UPDATE vault_config SET salt = ?, verifier_nonce = ?, verifier_ciphertext = ?, "
        "kdf_memory_cost = ?, kdf_iterations = ?, kdf_lanes = ? WHERE id = 1", values)
    return count


@dataclass
class _VaultSession:
    key: bytes
    expires_at: float
    version: int


class VaultSessions:
    """Keep derived keys in process memory, addressed by random HttpOnly session tokens."""

    def __init__(self, ttl_seconds: int = VAULT_SESSION_TTL_SECONDS, *, max_sessions: int = 32,
                 clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time) -> None:
        if ttl_seconds <= 0 or max_sessions < 1:
            raise ValueError("Session TTL and capacity must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._clock = clock
        self._wall_clock = wall_clock
        self._version = 0
        self._sessions: dict[str, _VaultSession] = {}
        self._lock = threading.Lock()

    def _purge_locked(self, now: float) -> int:
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            del self._sessions[token]
        return len(expired)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_locked(self._clock())

    def issue(self, key: bytes, *, replace_token: str | None = None) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = self._clock()
            self._purge_locked(now)
            self._sessions.pop(replace_token, None)
            if len(self._sessions) >= self._max_sessions:
                oldest = min(self._sessions, key=lambda value: self._sessions[value].expires_at)
                del self._sessions[oldest]
            self._version += 1
            self._sessions[token] = _VaultSession(key=key, expires_at=now + self._ttl_seconds, version=self._version)
        return token

    def get_key(self, token: str | None) -> bytes | None:
        with self._lock:
            self._purge_locked(self._clock())
            session = self._sessions.get(token)
            return session.key if session else None

    def status(self, token: str | None) -> dict[str, object]:
        """Public timing metadata only: never expose a token or derived key."""
        with self._lock:
            now = self._clock()
            self._purge_locked(now)
            session = self._sessions.get(token)
            remaining = session.expires_at - now if session else 0
            return {"unlocked": session is not None, "remaining_seconds": remaining,
                    "expires_at_ms": int((self._wall_clock() + remaining) * 1000) if session else None,
                    "session_version": session.version if session else 0}

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._purge_locked(self._clock())
            self._sessions.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


class UnlockAttemptLimiter:
    """Throttle repeated unlock attempts within this local application process."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300, cooldown_seconds: int = 30) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds
        self._failed_at: list[float] = []
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def check_allowed(self) -> None:
        with self._lock:
            if time.monotonic() < self._blocked_until:
                raise VaultRateLimited("解鎖嘗試過多，請稍後再試")

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._failed_at = [stamp for stamp in self._failed_at if now - stamp < self._window_seconds]
            self._failed_at.append(now)
            if len(self._failed_at) >= self._max_attempts:
                self._blocked_until = now + self._cooldown_seconds

    def record_success(self) -> None:
        with self._lock:
            self._failed_at.clear()
            self._blocked_until = 0.0
