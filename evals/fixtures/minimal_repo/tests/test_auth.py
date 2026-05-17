"""Tests for the auth module."""
import pytest

from src.auth.login import login, logout


def test_login_returns_token():
    assert login("alice", "pw").startswith("token-for-")


def test_login_rejects_empty():
    with pytest.raises(ValueError):
        login("", "")


def test_logout_smoke():
    logout("token-for-alice")
