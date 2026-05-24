# Getting Started

## Requirements

- Python **3.12 or 3.13** (3.14 is excluded until dependent wheels catch up)
- **`GP_ACCESS_TOKEN`** or **`Q2GOOGLE_GOPRO_ACCESS_TOKEN`** — your GoPro cloud access token (loaded by `Q2GoogleSettings` and passed to `AsyncGoProClient`)
- Google OAuth **installed-app** credentials (`client_secret.json` from [Google Cloud Console](https://console.cloud.google.com))
- A writable path for the authorized user token (`token.json` by default)

## Installation

=== "pip"

    ```bash
    pip install q2google
    ```

=== "uv"

    ```bash
    uv add q2google
    ```

## CLI quick start

```bash
export GP_ACCESS_TOKEN=<your-gopro-token>

q2google sync \
  --start-date 2026-01-08 \
  --end-date   2026-01-09 \
  --credentials client_secret.json \
  --token       token.json
```

On first run Google will open a browser for OAuth consent. The token is saved to `token.json` and reused on subsequent runs.

## Library quick start

```python
import asyncio
from datetime import datetime

from gopro_api import AsyncGoProClient

from q2google import (
    GoProToPhotosSync,
    GooglePhotosClient,
    GooglePhotosOAuth,
    JsonFileBackend,
    get_settings,
)
from q2google.gphotos.api import GooglePhotosAPI
from q2google.gphotos.models import PhotosScopes


async def main() -> None:
    oauth = GooglePhotosOAuth(
        client_secrets_file="client_secret.json",
        scopes=[PhotosScopes.READ_AND_APPEND],
        token_file="token.json",
    )

    cfg = get_settings()

    async with (
        AsyncGoProClient(access_token=cfg.gopro_access_token) as gopro,
        GooglePhotosAPI(credentials=oauth) as api,
    ):
        photos = GooglePhotosClient(api=api)
        backend = JsonFileBackend(root_dir=".q2google_sessions")

        syncer = GoProToPhotosSync(
            gopro=gopro,
            photos=photos,
            state_backend=backend,
        )

        responses = await syncer.sync_date_range(
            start_date=datetime(2026, 1, 8),
            end_date=datetime(2026, 1, 9),
            session_id="my-session",
        )
        print(f"Created {len(responses)} batch(es).")


asyncio.run(main())
```

## Resuming a session

Pass the same `session_id` on subsequent runs. `GoProToPhotosSync` loads the persisted `SessionState` and skips already-completed items:

```python
responses = await syncer.sync_date_range(
    start_date=datetime(2026, 1, 8),  # ignored when resuming
    end_date=datetime(2026, 1, 9),    # ignored when resuming
    session_id="my-session",          # same key → resumes from checkpoint
)
```

## State backends

By default sessions are saved to the local filesystem under `.q2google_sessions`.
q2google also ships a **MongoDB backend** and supports custom backends via the
`SyncStateBackend` protocol.

Set `Q2GOOGLE_STATE_URI` to switch backends without any code changes:

```dotenv
# MongoDB backend (requires: pip install q2google[mongo])
Q2GOOGLE_STATE_URI=mongodb://localhost:27017/q2google
```

See the [Backends guide](backends.md) for installation, configuration, collection
schemas, and instructions for writing your own backend.

## Stage completion hook

`on_stage_complete` is called after each of the three pipeline stages. Use it to report progress, emit metrics, or trigger side-effects:

```python
from q2google.state.base import SessionState, StageKey
from q2google.photos import MediaItemBatchCreateResponse


async def report(
    stage: StageKey,
    state: SessionState,
    responses: list[MediaItemBatchCreateResponse] | None,
) -> None:
    print(f"[{stage}] items={len(state.items)} stages={state.stages}")


responses = await syncer.sync_date_range(
    start_date=datetime(2026, 1, 8),
    end_date=datetime(2026, 1, 9),
    session_id="my-session",
    on_stage_complete=report,
)
```

## Next steps

- Read the [CLI reference](cli.md) for all available options.
- Review the [Configuration](configuration.md) page for environment-variable settings.
- See the [API Reference](api/index.md) for full symbol documentation.
