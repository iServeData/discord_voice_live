# Changelog

## 1.1.0 (2026-10-18)

- First public version of two jobs that have run in production since October 2026.
- Settings use generic names (`VOICE_GUILD_ID`, `VOICE_GROUPS`, `VOICE_OUT`, `VOICE_GRACE_SECONDS`).
- The announcer's events (schedule, windows, links, optional player count) moved from the code to
  `events.json`, with validation and a `--check` mode. Posting behavior is unchanged.
- One installer for both jobs, `deploy/announce_check.sh` for checks and test posts, example settings.
