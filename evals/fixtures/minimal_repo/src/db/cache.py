"""In-memory query cache."""


class Cache:
    def __init__(self, max_entries: int = 1024) -> None:
        self._data: dict = {}
        self.max_entries = max_entries

    def get(self, key: str):
        return self._data.get(key)

    def put(self, key: str, value) -> None:
        if len(self._data) >= self.max_entries:
            self._data.pop(next(iter(self._data)))
        self._data[key] = value
