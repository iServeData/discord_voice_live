# Discord voice live

Two small jobs for a community website and Discord server, with no bot and no bot token:

1. **`discord_voice_live.py`** reads your server's public Discord widget once a minute and publishes
   `voice.json`: **head counts only** per group of voice channels, plus when each group was last occupied.
   A website can use it to show "Live now · 6 in voice" on its event cards.
2. **`voice_live_announce.py`** (optional) reads that file and posts one Discord message per session,
   through a webhook, once enough people show up for a scheduled event. It edits the message with the
   current count while live, and marks it ended with the peak count and the next start time.

No usernames, avatars or member IDs are ever written, and website visitors' browsers never contact Discord.

```
Discord widget.json ──(every 60 s)──▶ discord-voice-live (user dvoice) ──▶ <site>/live/voice.json
                                                                                │
                                         website event cards ◀──────────────────┤
                                                                                ▼
                      Discord channel ◀── webhook ── voice-live-announce (every minute, DynamicUser)
                                                       └ optional: WARDOGS status.json for player count
```

## Requirements

- Linux with systemd 247 or newer, Python 3.9 or newer (standard library only; the tests need 3.11+).
- In Discord: **Server Settings → Widget → Enable Server Widget**, and on each counted voice channel
  `@everyone` needs **View Channel** and **Connect** (the widget only lists channels anyone can join).
- A web server that serves a folder of your site as static files.

## Install

```
git clone https://github.com/iServeData/discord_voice_live.git
cd discord_voice_live
sudo bash deploy/install.sh /var/www/example/live              # head counts only
sudo bash deploy/install.sh /var/www/example/live --announce   # plus Discord announcements
```

The first run creates the settings in `/etc/discord-voice-live/` from the examples and tells you what to fill in:

1. `voice.env`: your server ID and channel groups (see below), then `sudo systemctl enable --now discord-voice-live.timer`.
2. With `--announce`: the webhook URL in `announce.env` and your schedule in `events.json`, then check them
   with `sudo bash deploy/announce_check.sh`, and `sudo systemctl enable --now voice-live-announce.timer`.

To update later: `git pull`, then `sudo bash deploy/install.sh` (the folder and the announcer choice are
remembered, and existing settings are never overwritten).

If you deploy the site with `rsync --delete`, exclude the folder (`--exclude /live/`) and don't change
its owner, or each deploy deletes the file until the next run.

## Voice groups (`voice.env`)

```
VOICE_GUILD_ID=000000000000000000
VOICE_GROUPS=friday=000000000000000011;tactical=000000000000000021,000000000000000022
VOICE_GRACE_SECONDS=600
```

Instead of `VOICE_GROUPS`, the groups can come from a shared schedule file with
`VOICE_SCHEDULE_FILE` (see "Shared schedule file" below). A group's count is the total of its channels. People can leave and come back within `VOICE_GRACE_SECONDS`
without starting a new session. Copy IDs with Discord's Developer Mode (right-click → Copy ID).

The output format is described in [docs/voice_json.md](docs/voice_json.md).

## Events (`events.json`)

```json
{
  "timezone": "America/Los_Angeles",
  "events": {
    "tactical": {
      "title": "Tactical night",
      "voice_group": "tactical",
      "slots": [{ "days": ["sat", "sun", "mon", "tue", "wed", "thu"], "time": "18:15" },
                { "days": ["sat"], "time": "10:00" }],
      "early_minutes": 15, "window_minutes": 30, "cap_minutes": 120, "grace_minutes": 10,
      "channels": ["000000000000000021", "000000000000000022"],
      "url": "https://example.org/tactical/",
      "server_status_file": "/var/www/example/wardogs/data/status.json",
      "seed_goal": 20
    }
  }
}
```

| Key | Default | Meaning |
|---|---|---|
| `title` | the event name | Shown in the post |
| `voice_group` | the event name | Which group from `VOICE_GROUPS` to watch |
| `slots` | required | Days (`mon`…`sun`) and wall-clock start times in `timezone`; daylight saving is handled |
| `early_minutes` | `15` | A session can start this long before the scheduled time |
| `window_minutes` | `30` | …or up to this long after it |
| `cap_minutes` | `120` | The post is marked ended at the latest this long after the start |
| `grace_minutes` | `10` | Ended after the channels have been empty this long |
| `min_voice` | `MIN_VOICE` (2) | People in voice before it posts |
| `channels` | from voice data | Order to pick the "Hop in" channel when counts tie |
| `url` | none | Info link in the post |
| `server_status_file`, `seed_goal` | none | Optional game-server player count from a [WARDOGS status monitor](https://github.com/iServeData/wardogs_status_monitor) file |
| `webhook_env` | `<NAME>_WEBHOOK_URL` | Setting that sends this event to its own channel |
| `enabled` | `true` | `false` keeps the event in the file without announcing it |

An event only posts from real voice data. If the data is missing or older than four minutes, it stays
quiet; there is no "scheduled time" fallback, so it never announces an empty session. The widget is
cached by Discord for a few minutes, so posts trail actual attendance by roughly five to seven minutes,
and invisible members aren't counted.

## Shared schedule file (optional)

If a website shows the same schedule, keep the days and times in one file that both read, instead
of copying them. Point `events.json` at it with `schedule_file`; each event then takes its schedule
from the event with the same name there (or the one named by `schedule_event`):

```json
{
  "schedule_file": "/var/www/example/data/schedule.json",
  "events": {
    "tactical": { "server_status_file": "/var/www/example/wardogs/data/status.json" },
    "friday":   { "enabled": false }
  }
}
```

- The schedule file has the same layout as `events.json` (`timezone`, then `events`). Other keys in
  it, such as calendar text for the website, are ignored.
- These keys can live in either file, but not both: `timezone`, `title`, `voice_group`, `slots`,
  `early_minutes`, `window_minutes`, `cap_minutes`, `grace_minutes`, `channels`, `url`, `seed_goal`.
  Setting one in both is an error, so there is only ever one place to change it.
- Server-side keys stay in `events.json`: `server_status_file`, `min_voice`, `webhook_env`, `enabled`.
- The file is read on every run, so a change takes effect within a minute. If it is missing or
  broken, the announcer logs why and posts nothing until it is fixed.
- `sudo bash deploy/announce_check.sh` shows each event's slots and which file they came from.

The voice collector can read the same file: set `VOICE_SCHEDULE_FILE` in `voice.env` and every
event with `channels` becomes a group (named by `voice_group`, else the event name). You can still
add groups in `VOICE_GROUPS`, but a group in both is an error. If the file is briefly missing or
broken, the collector keeps the groups from the last `voice.json` and logs the problem.

See `config/schedule.json.example`.

## Announcer settings (`announce.env`, mode 600)

| Variable | Default | Meaning |
|---|---|---|
| `WEBHOOK_URL` | required | Channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL |
| `<NAME>_WEBHOOK_URL` | blank | Optional per-event channel, e.g. `FRIDAY_WEBHOOK_URL` |
| `ANNOUNCE_EVENTS` | blank (all enabled) | Comma-separated event names to announce |
| `MIN_VOICE` | `2` | Default people in voice before posting |
| `PING_ROLE_ID` | blank | Opt-in role pinged on the first post only; edits never ping |
| `UPDATE_MIN` | `5` | Minutes between count edits while live |

## Day to day

```
systemctl list-timers 'discord-voice-live*' 'voice-live-announce*' --no-pager
journalctl -u discord-voice-live.service -n 5 --no-pager -o cat
journalctl -u voice-live-announce.service -n 20 --no-pager -o cat
sudo bash deploy/announce_check.sh --dry-run    # what it would post right now
sudo bash deploy/announce_check.sh --test       # one test message (delete it afterwards)
sudo bash deploy/uninstall.sh                   # remove (add --purge to delete the settings too)
```

Both services are timer jobs, so `systemctl status` shows `inactive (dead)` between runs; that's normal.

## Security

- The collector runs as `dvoice` with a read-only system, no capabilities and one writable folder. It needs
  no token; the widget is public.
- The announcer runs as a throwaway `DynamicUser`, can only write its own state folder, and only makes
  outbound HTTPS requests to the webhook. Mentions are locked down (`allowed_mentions`), so a channel or
  event name can't ping anyone.
- The webhook URL is a secret: keep `announce.env` at mode 600 and never commit it. See [SECURITY.md](SECURITY.md).

## Development

```
python3 -m pip install --require-hashes --no-deps -r requirements-dev.lock
python3 -m pytest -q
python3 tools/check_generic.py
```

## License

[MIT](LICENSE)
