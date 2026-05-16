"""Unit tests for app/core/security.py."""

from __future__ import annotations

import time

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_password_produces_bcrypt_hash() -> None:
    hashed = hash_password("mysecret")
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")


def test_hash_password_is_not_plaintext() -> None:
    plain = "plaintext_pw"
    assert hash_password(plain) != plain


def test_verify_password_correct_plain() -> None:
    plain = "correct_password"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_wrong_plain() -> None:
    hashed = hash_password("real_password")
    assert verify_password("wrong_password", hashed) is False


def test_hash_password_different_hashes_per_call() -> None:
    # bcrypt salts each call — two hashes of the same input must differ
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


# ── JWT creation and decoding ─────────────────────────────────────────────────

def test_create_access_token_returns_string() -> None:
    token = create_access_token("user-uuid-123")
    assert isinstance(token, str)
    assert len(token) > 10


def test_decode_access_token_round_trips_subject() -> None:
    subject = "abc-def-ghi"
    token = create_access_token(subject)
    payload = decode_access_token(token)
    assert payload["sub"] == subject


def test_create_access_token_with_extra_claims() -> None:
    token = create_access_token("u1", extra_claims={"role": "admin"})
    payload = decode_access_token(token)
    assert payload["role"] == "admin"
    assert payload["sub"] == "u1"


def test_decode_access_token_raises_on_tampered_token() -> None:
    token = create_access_token("user")
    tampered = token[:-4] + "xxxx"
    with pytest.raises(JWTError):
        decode_access_token(tampered)


def test_decode_access_token_raises_on_garbage_input() -> None:
    with pytest.raises(JWTError):
        decode_access_token("not.a.jwt")


def test_decode_access_token_contains_exp_field() -> None:
    token = create_access_token("user")
    payload = decode_access_token(token)
    assert "exp" in payload
    # exp must be in the future
    assert payload["exp"] > time.time()
