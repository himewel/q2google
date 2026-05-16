# API Reference

All public symbols are importable directly from the top-level `q2google` package:

```python
from q2google import (
    GoProToPhotosSync,
    GooglePhotosClient,
    GooglePhotosOAuth,
    JsonFileBackend,
    SessionState,
    SyncStateBackend,
    Q2GoogleSettings,
    get_settings,
)
```

## Public symbol map

| Symbol | Module | Description |
|--------|--------|-------------|
| [`GoProToPhotosSync`](sync.md) | `q2google.sync` | Main orchestrator; runs discovery → transfer → create. |
| [`GooglePhotosClient`](photos.md) | `q2google.photos` | Resumable upload facade (`upload_file_path`, `create_media_items`). |
| [`GooglePhotosOAuth`](gphotos.md) | `q2google.gphotos.auth` | Load, refresh, or obtain Google OAuth credentials. |
| [`JsonFileBackend`](state.md) | `q2google.state.local` | File-based `SyncStateBackend`; one JSON per session under a root directory. |
| [`SessionState`](state.md) | `q2google.state.base` | Full persisted session document (`to_dict` / `from_dict`). |
| [`SyncStateBackend`](state.md) | `q2google.state.base` | Protocol — implement `load` / `save` to plug in any storage layer. |
| [`Q2GoogleSettings`](config.md) | `q2google.config` | Pydantic settings; batch sizes, timeouts, and paths with env-var overrides. |
| [`get_settings`](config.md) | `q2google.config` | Return a singleton `Q2GoogleSettings` from environment / `.env`. |

## Lower-level symbols

| Symbol | Module | Description |
|--------|--------|-------------|
| [`GooglePhotosAPI`](gphotos.md) | `q2google.gphotos.api` | Thin `aiohttp` wrapper for Library v1. |
| [`GooglePhotoLibraryPort`](gphotos.md) | `q2google.gphotos.api` | Protocol matching `GooglePhotosAPI`; implement for testing. |
| [`PhotosScopes`](gphotos.md) | `q2google.gphotos.models` | Enum of OAuth scopes (`READ_AND_APPEND`, `READ_ONLY`, `APPEND_ONLY`). |
