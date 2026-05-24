# CLI Reference

## `q2google sync`

Sync GoPro cloud media to Google Photos for a capture date range.

```
q2google sync [OPTIONS]
```

### Required options

| Option | Description |
|--------|-------------|
| `--start-date DATE` | First capture date to include (`YYYY-MM-DD`). |
| `--end-date DATE` | Last capture date to include (`YYYY-MM-DD`). |

### Authentication options

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--credentials PATH` | `Q2GOOGLE_CREDENTIALS_PATH` | `client_secret.json` | Google OAuth installed-app client secrets JSON. |
| `--token PATH` | `Q2GOOGLE_TOKEN_PATH` | `token.json` | Authorized user token file (created on first run). |

### Session options

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--state-dir PATH` | `Q2GOOGLE_STATE_DIR` | `.q2google_sessions` | Root directory for per-session state; each session is stored as a subdirectory containing `meta.json`, `items/`, and `batches/`. |
| `--session-id TEXT` | `Q2GOOGLE_SESSION_ID` | auto-generated | Stable identifier; reuse to resume an interrupted run. |

### Transfer options

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--batch-size INT` | `Q2GOOGLE_SYNC_BATCH_SIZE` | `10` | Items per transfer cycle for **new** sessions (ignored when resuming — persisted value wins). |

### Behaviour options

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--fail-fast / --no-fail-fast` | `Q2GOOGLE_FAIL_FAST` | `false` | Stop on first error after persisting state. |
| `--log-level LEVEL` | `Q2GOOGLE_LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

### Examples

```bash
# Minimal — sync a single day
q2google sync --start-date 2026-01-08 --end-date 2026-01-08

# Custom credentials and token paths
q2google sync \
  --start-date 2026-01-01 \
  --end-date   2026-01-31 \
  --credentials /secrets/client_secret.json \
  --token       /secrets/token.json

# Resume a named session (start/end dates are ignored)
q2google sync \
  --start-date 2026-01-01 \
  --end-date   2026-01-31 \
  --session-id january-2026

# Verbose output with a custom state directory
q2google sync \
  --start-date 2026-01-08 \
  --end-date   2026-01-09 \
  --state-dir  /tmp/q2google \
  --log-level  DEBUG
```

## Environment variable precedence

All options can be set via environment variables with the `Q2GOOGLE_` prefix. The GoPro token also accepts `GP_ACCESS_TOKEN` or `Q2GOOGLE_GOPRO_ACCESS_TOKEN` (see [Configuration](configuration.md)). CLI flags always override environment variables.

q2google also reads a `.env` file from the working directory via `pydantic-settings`. See [Configuration](configuration.md) for the full reference.
