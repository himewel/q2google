# q2google

Sync media from **GoPro cloud** into **Google Photos** for a capture date range using **resumable session state** on disk (JSON) via ``SyncStateBackend``.

## Requirements

- Python **3.12 or 3.13** (3.14 is excluded until dependent wheels catch up)
- [uv](https://docs.astral.sh/uv/) for installs and tasks
- Google OAuth **installed app** credentials (`client_secret.json` from Google Cloud Console)
- A writable path for the user token (`token.json` by default)

## Install (development)

From the repository root:

```bash
uv sync
```

## CLI

Run with defaults for state directory (`.q2google_sessions`) and a new session UUID each run unless you pass `--session-id` or set `Q2GOOGLE_SESSION_ID`:

```bash
uv run q2google sync \
  --start-date 2026-01-08 \
  --end-date 2026-01-09 \
  --credentials client_secret.json \
  --token token.json
```

Useful options:

| Option | Description |
|--------|-------------|
| `--state-dir` | JSON session root (default: `.q2google_sessions` or `Q2GOOGLE_STATE_DIR`) |
| `--session-id` | Stable id to resume a run (`Q2GOOGLE_SESSION_ID` if unset) |
| `--batch-size` | Files per cycle for **new** sessions; ignored when resuming (persisted session wins) |
| `--fail-fast` | Stop on first error after persisting state |
| `--log-level DEBUG` | Verbose logging |

## Library

```python
from gopro_api import AsyncGoProClient

from q2google import (
    GoProToPhotosSync,
    GooglePhotosClient,
    GooglePhotosOAuth,
    JsonFileBackend,
)
from q2google.gphotos.api import GooglePhotosAPI
from q2google.gphotos.models import PhotosScopes

# Wire credentials, async clients, JsonFileBackend + session_id for sync_date_range.
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module layout and extension points.

## Configuration

Defaults and CLI fallbacks are defined by [`Q2GoogleSettings`](q2google/config.py) (Pydantic **BaseSettings**). Values load from environment variables with prefix **`Q2GOOGLE_`** and from a **`.env`** file in the working directory.

Common variables:

| Variable | Purpose |
|----------|---------|
| `Q2GOOGLE_CREDENTIALS_PATH` | Google OAuth client secrets JSON path |
| `Q2GOOGLE_TOKEN_PATH` | Authorized user token path |
| `Q2GOOGLE_STATE_DIR` | JSON session state directory |
| `Q2GOOGLE_SESSION_ID` | Default session id when `--session-id` is omitted |
| `Q2GOOGLE_SYNC_BATCH_SIZE` | Transfer batch size for **new** sessions |
| `Q2GOOGLE_PHOTOS_LIBRARY_BATCH_SIZE` | Items per `batchCreate` (1–50) |
| `Q2GOOGLE_FAIL_FAST` | `true` / `false` |
| `Q2GOOGLE_LOG_LEVEL` | e.g. `INFO`, `DEBUG` |
| `Q2GOOGLE_GOOGLE_PHOTOS_TIMEOUT_SECONDS` | Library API request timeout |
| `Q2GOOGLE_DOWNLOAD_CHUNK_SIZE_BYTES` | CDN stream chunk size |

See `q2google.config.Q2GoogleSettings` for the full list and defaults.

## Development

```bash
task format   # Ruff import fix + format
task lint     # Ruff check + format check (no writes)
task test     # Pytest with coverage on `q2google`
```

## License

See repository metadata (add a `LICENSE` file if needed).
