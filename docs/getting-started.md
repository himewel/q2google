# Getting Started

## Requirements

- Python **3.12 or 3.13** (3.14 is excluded until dependent wheels catch up)
- **`GP_ACCESS_TOKEN`** environment variable — your GoPro cloud access token
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
)
from q2google.gphotos.api import GooglePhotosAPI
from q2google.gphotos.models import PhotosScopes


async def main() -> None:
    oauth = GooglePhotosOAuth(
        client_secrets_file="client_secret.json",
        scopes=[PhotosScopes.READ_AND_APPEND],
        token_file="token.json",
    )

    async with (
        AsyncGoProClient() as gopro,
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

## Custom state backend

Implement `SyncStateBackend` to persist sessions in any storage layer (database, object store, etc.):

```python
from q2google import SessionState, SyncStateBackend


class RedisBackend:
    def load(self, session_id: str) -> SessionState | None:
        raw = redis_client.get(session_id)
        return SessionState.from_dict(json.loads(raw)) if raw else None

    def save(self, state: SessionState) -> None:
        redis_client.set(state.session_id, json.dumps(state.to_dict()))
```

Pass it directly to `GoProToPhotosSync(state_backend=RedisBackend())`. No other changes required.

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
