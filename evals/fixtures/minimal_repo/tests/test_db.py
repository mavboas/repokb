"""Tests for the db module."""
from src.db.query import get_user, put_user
from src.db.cache import Cache


def test_put_and_get_roundtrip():
    put_user("u1", {"name": "alice"})
    assert get_user("u1") == {"name": "alice"}


def test_cache_evicts_oldest():
    c = Cache(max_entries=2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)
    assert c.get("a") is None
    assert c.get("c") == 3
