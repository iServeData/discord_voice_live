# Changelog

## 1.2.0 (2026-10-23)

- Shared schedule file: `events.json` can name a `schedule_file` that holds the schedule keys
  (timezone, slots, windows, channels, link, seed goal), so a website and the announcer read the
  same days and times. A key set in both files is an error. `--check` shows each event's slots and
  where they came from.
- The voice collector can take its groups from the same file with `VOICE_SCHEDULE_FILE`. If the
  file is briefly missing or broken it keeps the groups from the last `voice.json`.
- `seed_goal` is checked to be a whole number.

## 1.1.0 (2026-10-18)

- First public version of two jobs that have run in production since October 2026.
- Settings use generic names (`VOICE_GUILD_ID`, `VOICE_GROUPS`, `VOICE_OUT`, `VOICE_GRACE_SECONDS`).
- The announcer's events (schedule, windows, links, optional player count) moved from the code to
  `events.json`, with validation and a `--check` mode. Posting behavior is unchanged.
- One installer for both jobs, `deploy/announce_check.sh` for checks and test posts, example settings.
