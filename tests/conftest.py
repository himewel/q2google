"""Shared pytest fixtures for q2google tests.

The ``backend`` fixture is parametrized over all built-in :class:`~q2google.state.base.SyncStateBackend`
implementations.  Any test that accepts ``backend`` runs once per backend automatically:

- **json** — :class:`~q2google.state.local.JsonFileBackend` backed by a ``tmp_path`` directory.
- **mongo** — :class:`~q2google.state.mongo.MongoBackend` backed by ``mongomock``; skipped
  automatically when either ``mongomock`` or ``pymongo`` is not installed.
"""

from __future__ import annotations

import pytest

from q2google.state.base import SyncStateBackend


def _json_backend(tmp_path):
    from q2google.state.local import JsonFileBackend

    return JsonFileBackend(tmp_path)


def _mongo_backend():
    mongomock = pytest.importorskip("mongomock", reason="mongomock not installed — skipping mongo backend tests")
    pytest.importorskip("pymongo", reason="pymongo not installed — skipping mongo backend tests")
    from q2google.state.mongo import MongoBackend

    uri = "mongodb://localhost:27017/q2google_test"
    with mongomock.patch(servers=("localhost:27017",)):
        yield MongoBackend(uri)


@pytest.fixture(params=["json", "mongo"])
def backend(request, tmp_path) -> SyncStateBackend:
    """Yield a :class:`~q2google.state.base.SyncStateBackend` for each registered implementation.

    Tests parametrized over this fixture run once per backend.  The ``mongo`` variant is
    skipped automatically when ``mongomock`` or ``pymongo`` is not installed.
    """
    if request.param == "json":
        yield _json_backend(tmp_path)
    else:
        yield from _mongo_backend()
