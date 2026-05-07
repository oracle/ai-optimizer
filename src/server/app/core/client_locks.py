"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Per-client serialisation primitives shared across endpoints that mutate the
embedding temp directory. Lives in ``core`` to break the embed↔oci circular
import that previously forced function-local imports.
"""

import asyncio
import contextlib
from collections import OrderedDict
from dataclasses import dataclass, field

from server.app.core.file_utils import safe_filename
from server.app.core.settings import settings


@dataclass
class _LockEntry:
    """Registry entry pairing a per-client lock with an in-use refcount.

    `users` counts everyone currently inside `_client_lock(client)` —
    both the holder and any queued waiters. The count is mutated only
    under `_client_locks_guard`, so eviction can safely treat
    ``users == 0`` as "no in-flight request relies on this entry" and
    skip everything else. This is strictly tighter than checking
    ``lock.locked()``: ``asyncio.Lock`` has a brief handoff window
    between ``release()`` and a woken waiter resuming where ``locked()``
    is False even though a waiter is queued, and evicting in that
    window would let a subsequent request for the same client allocate
    a second Lock and run concurrently with the still-pending waiter.
    """

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


_client_promotion_locks: OrderedDict[str, _LockEntry] = OrderedDict()
_client_locks_guard = asyncio.Lock()


@contextlib.asynccontextmanager
async def _client_lock(client: str):
    """Per-client serialisation around shared embedding temp dir mutations.

    Indexes by the same canonical form `get_temp_directory` uses
    (`safe_filename(client)`) so two raw header values that resolve to
    the same on-disk directory share one lock. Without this, e.g.
    ``Client: team/a`` and ``Client: a`` would lock independently while
    operating on the same files in `<base>/a/embedding`.

    Caps the registry at ``settings.max_clients`` entries with LRU
    eviction. Entries with ``users > 0`` are skipped during eviction
    so an in-flight request — holder *or* queued waiter — retains its
    mutual-exclusion guarantee even when the registry is under
    pressure.
    """
    key = safe_filename(client)
    async with _client_locks_guard:
        entry = _client_promotion_locks.get(key)
        if entry is None:
            cap = max(1, settings.max_clients)
            while len(_client_promotion_locks) >= cap:
                evict_key = next(
                    (k for k, e in _client_promotion_locks.items() if e.users == 0),
                    None,
                )
                if evict_key is None:
                    # Every entry is in use; accept temporary growth
                    # rather than break in-flight serialisation.
                    break
                _client_promotion_locks.pop(evict_key)
            entry = _LockEntry()
            _client_promotion_locks[key] = entry
        else:
            _client_promotion_locks.move_to_end(key)
        # Increment under the guard so a waiter is counted *before* it
        # awaits `entry.lock` — eviction will see users >= 1 even
        # during the asyncio release/resume handoff window.
        entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        async with _client_locks_guard:
            entry.users -= 1
