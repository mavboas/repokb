# Database

User records are stored via `src/db/query.py` (`get_user`, `put_user`). The
backing store is currently a process-local dict; production swaps this for
a SQL backend.

A read-through cache (`src/db/cache.py`) sits in front of every query and
evicts the oldest entry once `max_entries` is reached.
