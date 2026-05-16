# Configuration

All settings are managed by `Q2GoogleSettings` — a [Pydantic `BaseSettings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) model that reads values from the environment and a `.env` file in the working directory.

## GoPro credentials

| Variable | Required | Description |
|----------|----------|-------------|
| `GP_ACCESS_TOKEN` | **Yes** | GoPro cloud access token; read directly by `AsyncGoProClient`. |

## Google OAuth

| Variable | Default | Description |
|----------|---------|-------------|
| `Q2GOOGLE_CREDENTIALS_PATH` | `client_secret.json` | Path to the OAuth installed-app client secrets JSON downloaded from Google Cloud Console. |
| `Q2GOOGLE_TOKEN_PATH` | `token.json` | Path to the authorized user token. Created on first run; reused on subsequent runs. |

## Session state

| Variable | Default | Description |
|----------|---------|-------------|
| `Q2GOOGLE_STATE_DIR` | `.q2google_sessions` | Root directory for per-session JSON state files. |
| `Q2GOOGLE_SESSION_ID` | _(auto)_ | Default session identifier when `--session-id` is omitted from the CLI. |

## Transfer tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `Q2GOOGLE_SYNC_BATCH_SIZE` | `10` | Number of items per transfer cycle for **new** sessions. Ignored when resuming — the persisted value wins. |
| `Q2GOOGLE_PHOTOS_LIBRARY_BATCH_SIZE` | `50` | Items per `batchCreate` call (1–50, Google Photos API limit). |
| `Q2GOOGLE_DOWNLOAD_CHUNK_SIZE_BYTES` | `8388608` | CDN stream chunk size in bytes (default 8 MiB). |
| `Q2GOOGLE_GOOGLE_PHOTOS_TIMEOUT_SECONDS` | `120` | Request timeout for Google Photos Library API calls. |

## Behaviour

| Variable | Default | Description |
|----------|---------|-------------|
| `Q2GOOGLE_FAIL_FAST` | `false` | Stop on first transfer error after persisting state. |
| `Q2GOOGLE_LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## `.env` file

q2google loads a `.env` file from the current working directory automatically. Example:

```dotenv
GP_ACCESS_TOKEN=eyJ...

Q2GOOGLE_CREDENTIALS_PATH=secrets/client_secret.json
Q2GOOGLE_TOKEN_PATH=secrets/token.json
Q2GOOGLE_STATE_DIR=.sessions
Q2GOOGLE_LOG_LEVEL=DEBUG
```

## Programmatic access

```python
from q2google import Q2GoogleSettings, get_settings

# Singleton loaded from environment / .env
settings = get_settings()

# Override specific values in tests or scripts
settings = Q2GoogleSettings(
    credentials_path="path/to/client_secret.json",
    sync_batch_size=5,
)
```

See [`q2google.config`](api/config.md) in the API reference for all fields and their defaults.
