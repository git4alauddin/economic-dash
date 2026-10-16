"""Argon2id with bounded work and no password normalization/truncation."""

from contextlib import contextmanager
import re
from secrets import token_urlsafe
from threading import BoundedSemaphore
from unicodedata import category

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

HASHER = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
_WORKERS = BoundedSemaphore(2)  # At most two 64-MiB operations per API process.
_DUMMY_HASH = HASHER.hash(token_urlsafe(32))


class PasswordWorkBusy(RuntimeError):
    pass


def normalize_username(value: str) -> str:
    if not isinstance(value, str) or len(value) > 128 or not value.isascii():
        raise ValueError("Username must use 3-64 ASCII letters, digits, dots, hyphens or underscores.")
    name = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", name):
        raise ValueError("Username must use 3-64 ASCII letters, digits, dots, hyphens or underscores.")
    return name


def valid_password_input(value) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return False
    try:
        return len(value.encode("utf-8")) <= 512 and all(category(c) != "Cc" for c in value)
    except UnicodeError:
        return False


def validate_new_password(value: str) -> None:
    if not valid_password_input(value) or len(value) < 15 or not value.strip():
        raise ValueError("Password must contain 15-128 characters, with no control characters.")


@contextmanager
def _work():
    if not _WORKERS.acquire(blocking=False):
        raise PasswordWorkBusy("Password verification capacity reached.")
    try:
        yield
    finally:
        _WORKERS.release()


def hash_password(password: str) -> str:
    validate_new_password(password)
    with _work():
        return HASHER.hash(password)


def verify_password(encoded: str | None, password: str) -> bool:
    if not valid_password_input(password):
        return False
    usable = False
    try:
        params = extract_parameters(encoded) if isinstance(encoded, str) and len(encoded) <= 512 else None
        usable = params is not None and params.type == Type.ID and params.version == 19 and (
            8 <= params.memory_cost <= RFC_9106_LOW_MEMORY.memory_cost
            and 1 <= params.time_cost <= RFC_9106_LOW_MEMORY.time_cost
            and 1 <= params.parallelism <= RFC_9106_LOW_MEMORY.parallelism
            and 8 <= params.salt_len <= 64 and 16 <= params.hash_len <= 64)
    except (InvalidHashError, ValueError, TypeError):
        pass
    with _work():
        try:
            matched = HASHER.verify(encoded if usable else _DUMMY_HASH, password)
        except (VerificationError, InvalidHashError, UnicodeError):
            return False
    return usable and matched


def needs_rehash(encoded: str) -> bool:
    return HASHER.check_needs_rehash(encoded)
