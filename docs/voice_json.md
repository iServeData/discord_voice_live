# voice.json

Written atomically by `discord_voice_live.py` once a minute, mode 0644.

```json
{
  "version": 1,
  "checked_at": "2026-10-17T17:20:00Z",
  "observed_at": "2026-10-17T17:20:00Z",
  "source_ok": true,
  "grace_seconds": 600,
  "groups": {
    "tactical": {
      "listed": true,
      "count": 3,
      "channels": { "000000000000000021": 2, "000000000000000022": 1 },
      "occupied_since": "2026-10-17T17:02:00Z",
      "last_occupied_at": "2026-10-17T17:20:00Z"
    }
  }
}
```

| Field | Meaning |
|---|---|
| `checked_at` | When the job last ran |
| `observed_at` | When the widget was last read successfully. Treat the counts as unknown if this is old |
| `source_ok` | `false` when the last widget read failed; counts are then `null` and the times are kept |
| `listed` | `false` if any of the group's channels is missing from the widget (permissions changed) |
| `count`, `channels` | People in the group's channels, in total and per channel |
| `occupied_since` | Start of the current session, or `null` when empty for longer than `grace_seconds` |
| `last_occupied_at` | The last time anyone was in the group's channels |

A website card should show "live" only when `source_ok` is true, `observed_at` is recent (a few minutes),
`listed` is true and `count` is above zero. Fall back to the scheduled time otherwise.
