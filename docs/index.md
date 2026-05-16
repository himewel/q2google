# q2google

**q2google** syncs media from [GoPro cloud](https://gopro.com) into [Google Photos](https://photos.google.com) for a capture date range, with resumable session state so interrupted runs continue from the last checkpoint.

---

## How it works

Every sync run is split into three sequential pipeline stages:

```mermaid
sequenceDiagram
    participant Caller
    participant Sync as GoProToPhotosSync
    participant GoPro as AsyncGoProClient
    participant Photos as GooglePhotosClient
    participant Store as SyncStateBackend

    Caller->>Sync: sync_date_range(start, end, session_id)
    Sync->>Store: load(session_id)
    Store-->>Sync: SessionState or new
    Note over Sync: discovery
    Sync->>GoPro: list_media_items, get_download_url
    Sync->>Store: save(state)
    Note over Sync: transfer
    Sync->>Photos: upload_file_path per item
    Sync->>Store: save(state)
    Note over Sync: create
    Sync->>Photos: create_media_items_from_upload_sessions
    Sync->>Store: save(state)
    Sync-->>Caller: list of batch create responses
```

State is persisted through `SyncStateBackend` after each stage. Passing the same `session_id` on a subsequent run resumes from the last checkpoint — already-completed items are skipped.

---

## Quick links

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting Started](getting-started.md)**

    Install q2google and run your first sync in minutes.

- :material-console: **[CLI Reference](cli.md)**

    Full command-line interface documentation.

- :material-cog: **[Configuration](configuration.md)**

    Environment variables and settings reference.

- :material-sitemap: **[Architecture](ARCHITECTURE.md)**

    Module map and extension points.

- :material-api: **[API Reference](api/index.md)**

    Auto-generated documentation for all public symbols.

</div>
