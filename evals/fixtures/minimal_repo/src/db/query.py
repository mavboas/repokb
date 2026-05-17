"""DB query abstraction."""


def get_user(user_id: str) -> dict | None:
    """Fetch a user record by id."""
    return _fake_db.get(user_id)


def put_user(user_id: str, record: dict) -> None:
    _fake_db[user_id] = record


_fake_db: dict[str, dict] = {}
