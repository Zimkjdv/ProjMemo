"""Password-derived encryption and short-lived sessions for the local vault."""

from __future__ import annotations

from dataclasses import dataclass
import os
import secrets
import threading
import time
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id


MASTER_PASSWORD_MIN_LENGTH = 16
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

    salt = os.urandom(16)
    key = _derive_key(
        password,
        salt,
        memory_cost=KDF_MEMORY_COST,
        iterations=KDF_ITERATIONS,
        lanes=KDF_LANES,
    )
    verifier_nonce = os.urandom(12)
    verifier_ciphertext = AESGCM(key).encrypt(verifier_nonce, _VERIFIER, _VERIFIER_AAD)
    connection.execute(
        """
        INSERT INTO vault_config
            (id, salt, verifier_nonce, verifier_ciphertext,
             kdf_memory_cost, kdf_iterations, kdf_lanes)
        VALUES (1, ?, ?, ?, ?, ?, ?)
        """,
        (salt, verifier_nonce, verifier_ciphertext,
         KDF_MEMORY_COST, KDF_ITERATIONS, KDF_LANES),
    )
    return key


def unlock_vault(connection: Any, password: str) -> bytes:
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


@dataclass
class _VaultSession:
    key: bytes
    expires_at: float


class VaultSessions:
    """Keep derived keys in process memory, addressed by random HttpOnly session tokens."""

    def __init__(self, ttl_seconds: int = VAULT_SESSION_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, _VaultSession] = {}
        self._lock = threading.Lock()

    def issue(self, key: bytes) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = _VaultSession(key=key, expires_at=time.monotonic() + self._ttl_seconds)
        return token

    def get_key(self, token: str | None) -> bytes | None:
        if not token:
            return None
        now = time.monotonic()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if session.expires_at <= now:
                del self._sessions[token]
                return None
            return session.key

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
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
