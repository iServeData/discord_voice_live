#!/usr/bin/env python3
"""Post to Discord when a scheduled community session goes live, based on voice attendance.

Part of https://github.com/iServeData/discord_voice_live

Reads the head counts written by discord_voice_live.py (voice.json) and, optionally, a
WARDOGS status.json for the server's player count. It only announces from real voice data:
if the voice data is missing or old it stays quiet, so it never announces an empty session.

One post per session. While live it edits the post with the current head count (at most every
UPDATE_MIN minutes). When the session ends it edits the post to "ended" with the peak count
and the next start time. Edits never ping anyone.

Events (schedules, windows, links) come from EVENTS_FILE (see config/events.json.example).
Standard library only. Run by voice-live-announce.timer once a minute.
  --dry-run   print what it would do, change nothing
  --test      post a one-off test message to the webhook and exit
  --check     validate the settings and events file, then exit
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN = 60
STALE = 4 * MIN
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SNOWFLAKE = re.compile(r"^\d{17,20}$")
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
UA = "voice-live-announce/1.1 (+https://github.com/iServeData/discord_voice_live)"

ENV = os.environ.get
WEBHOOK = ENV("WEBHOOK_URL", "").strip()
ONLY = [g.strip() for g in (ENV("ANNOUNCE_EVENTS") or ENV("ANNOUNCE_GROUPS") or "").split(",") if g.strip()]
MIN_VOICE = int(ENV("MIN_VOICE", "2"))
PING_ROLE = ENV("PING_ROLE_ID", "").strip()
UPDATE_MIN = int(ENV("UPDATE_MIN", "5"))
EVENTS_FILE = ENV("EVENTS_FILE", "/etc/discord-voice-live/events.json")
VOICE_FILE = ENV("VOICE_FILE", "/var/www/html/live/voice.json")
STATE_DIR = ENV("STATE_DIRECTORY", "/var/lib/voice-live-announce").split(":")[0]
STATE_FILE = os.path.join(STATE_DIR, "state.json")
DRY = "--dry-run" in sys.argv


class ConfigError(Exception):
    pass


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- events file
def load_events(path):
    """Read and validate the events file. Returns (timezone, {name: event})."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e.strerror}") from None
    except ValueError as e:
        raise ConfigError(f"{path} isn't valid JSON: {e}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("events"), dict) or not doc["events"]:
        raise ConfigError(f"{path}: needs an \"events\" object with at least one event")
    try:
        tz = ZoneInfo(str(doc.get("timezone", "UTC")))
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"{path}: unknown timezone {doc.get('timezone')!r}") from None
    events = {}
    for name, e in doc["events"].items():
        where = f"{path}: event {name!r}"
        if not NAME.match(name) or not isinstance(e, dict):
            raise ConfigError(f"{where}: names are lowercase letters, digits, - or _")
        if e.get("enabled", True) is False:
            continue
        slots = []
        for s in e.get("slots") or []:
            m = HHMM.match(str(s.get("time", ""))) if isinstance(s, dict) else None
            days = s.get("days") if isinstance(s, dict) else None
            if not m or not isinstance(days, list) or not days or any(str(d).lower()[:3] not in DAYS for d in days):
                raise ConfigError(f"{where}: each slot needs \"days\" (mon..sun) and \"time\" (HH:MM, 24-hour)")
            slots.append((tuple(DAYS[str(d).lower()[:3]] for d in days), int(m.group(1)), int(m.group(2))))
        if not slots:
            raise ConfigError(f"{where}: needs at least one slot")
        ev = {"name": name, "title": str(e.get("title") or name)[:80], "slots": slots,
              "group": str(e.get("voice_group") or name),
              "url": str(e.get("url") or ""), "channels": [str(c) for c in e.get("channels") or []],
              "status_file": e.get("server_status_file") or None,
              "seed_goal": e.get("seed_goal"),
              "min_voice": int(e.get("min_voice", MIN_VOICE)),
              "webhook_env": str(e.get("webhook_env") or f"{name.upper().replace('-', '_')}_WEBHOOK_URL")}
        for key, default, lo, hi in (("early_minutes", 15, 0, 120), ("window_minutes", 30, 1, 720),
                                     ("cap_minutes", 120, 1, 1440), ("grace_minutes", 10, 1, 120)):
            v = e.get(key, default)
            if not isinstance(v, int) or not lo <= v <= hi:
                raise ConfigError(f"{where}: {key} must be a whole number from {lo} to {hi}")
            ev[key.split("_")[0]] = v
        if ev["cap"] < ev["window"]:
            raise ConfigError(f"{where}: cap_minutes must be at least window_minutes")
        if ev["url"] and not ev["url"].startswith(("https://", "http://")):
            raise ConfigError(f"{where}: url must start with https://")
        if not NAME.match(ev["group"]) or not all(SNOWFLAKE.match(c) for c in ev["channels"]):
            raise ConfigError(f"{where}: voice_group must be a group name from VOICE_GROUPS; channels are IDs")
        if ev["min_voice"] < 1:
            raise ConfigError(f"{where}: min_voice must be at least 1")
        events[name] = ev
    return tz, events


# --------------------------------------------------------------------------- inputs
def ts(s):
    """ISO-8601 -> unix seconds, or None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def group_data(voice, name, now):
    """The group's current counts, or None if the voice data is missing, failed or old."""
    if not isinstance(voice, dict) or voice.get("version") != 1 or voice.get("source_ok") is not True:
        return None
    obs = ts(voice.get("observed_at"))
    if not obs or abs(now - obs) > STALE:
        return None
    g = (voice.get("groups") or {}).get(name)
    if not isinstance(g, dict) or g.get("listed") is not True or not isinstance(g.get("count"), (int, float)):
        return None
    return {"count": int(g["count"]), "channels": g.get("channels") or {},
            "since": ts(g.get("occupied_since")), "last": ts(g.get("last_occupied_at"))}


def server_players(path, now):
    """'12/100' from a WARDOGS status.json, or None when missing or old."""
    d = load_json(path) if path else None
    if not isinstance(d, dict) or d.get("schema_version") != 1:
        return None
    gen = ts(d.get("generated_at"))
    cs = d.get("community_server") or {}
    p = cs.get("players") or {}
    at = ts(p.get("observed_at"))
    if not gen or abs(now - gen) > STALE or cs.get("state") != "responding" or not at \
            or abs(now - at) > STALE or not isinstance(p.get("current"), (int, float)):
        return None
    return f"{int(p['current'])}/{int(p['max'])}" if isinstance(p.get("max"), (int, float)) else str(int(p["current"]))


# --------------------------------------------------------------------------- schedule rules
def occurrences(ev, now, tz):
    """Scheduled starts (unix s) from yesterday to +8 days, in the events' wall-clock time."""
    today = datetime.fromtimestamp(now, tz).date()
    out = []
    for k in range(-1, 9):
        day = today + timedelta(days=k)
        for days, hh, mm in ev["slots"]:
            if day.weekday() in days:
                start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).timestamp()
                out.append((start, f"{day.isoformat()}T{hh:02d}:{mm:02d}"))
    return sorted(out)


def is_live(start, ev, g, now):
    """Live = people in voice now, and the session began between `early` before the start and
    the end of the start window, and the hard cap hasn't passed."""
    e, win_end, cap_end = start - ev["early"] * MIN, start + ev["window"] * MIN, start + ev["cap"] * MIN
    if now < e or not g or not g["since"] or not g["last"]:
        return False
    ongoing = (now - g["last"]) < ev["grace"] * MIN
    return ongoing and now < cap_end and g["since"] <= win_end and g["last"] >= e


def best_channel(ev, g):
    order = ev["channels"] or sorted(g["channels"])
    if not order:
        return None
    best = order[0]
    for cid in order:
        if (g["channels"].get(cid) or 0) > (g["channels"].get(best) or 0):
            best = cid
    return best


def dur(sec):
    m = max(0, int(sec // 60))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


# --------------------------------------------------------------------------- messages
def live_text(ev, g, players, start, ping):
    lines = []
    if ping and PING_ROLE:
        lines.append(f"<@&{PING_ROLE}>")
    lines.append(f"🟢 **{ev['title']} is live**")
    stats = f"{g['count']} in voice now"
    if players:
        stats += f" · server {players}" + (f" (seed goal: {ev['seed_goal']})" if ev["seed_goal"] else "")
    lines.append(stats)
    ch = best_channel(ev, g)
    if ch:
        lines.append(f"Hop in: <#{ch}>")
    lines.append(f"Scheduled <t:{int(start)}:t>" + (f" · info: <{ev['url']}>" if ev["url"] else ""))
    return "\n".join(lines)


def ended_text(ev, st, nxt):
    lines = [f"⚪ **{ev['title']} session ended**",
             f"Peak {st['peak']} in voice · ran {dur(st['last_seen'] - st['posted_at'])}"]
    if nxt:
        lines.append(f"Next: <t:{int(nxt)}:F> (<t:{int(nxt)}:R>)")
    if ev["url"]:
        lines.append(f"Info: <{ev['url']}>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- Discord webhook
def http(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def hook_for(ev):
    """Per-event webhook (e.g. BAR_WEBHOOK_URL), falling back to WEBHOOK_URL."""
    return ENV(ev["webhook_env"], "").strip() or WEBHOOK


def post(content, ping, hook=None):
    if DRY:
        log("[dry-run] POST:\n" + content)
        return "dry-run"
    allowed = {"parse": [], "roles": [PING_ROLE] if (ping and PING_ROLE) else []}
    msg = http("POST", (hook or WEBHOOK) + "?wait=true", {"content": content, "allowed_mentions": allowed})
    return msg.get("id")


def edit(msg_id, content, hook=None):
    if DRY or not msg_id or msg_id == "dry-run":
        log(f"[dry-run] EDIT {msg_id}:\n" + content)
        return
    http("PATCH", f"{hook or WEBHOOK}/messages/{msg_id}", {"content": content, "allowed_mentions": {"parse": []}})


def save_state(state):
    if DRY:
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE_FILE)


def valid_hook(url):
    return url.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/"))


# --------------------------------------------------------------------------- main loop
def run(now=None):
    try:
        tz, events = load_events(EVENTS_FILE)
    except ConfigError as e:
        log(f"events file problem: {e}")
        return 2
    if ONLY:
        unknown = [n for n in ONLY if n not in events]
        for n in unknown:
            log(f"ANNOUNCE_EVENTS names {n!r}, which isn't an enabled event in {EVENTS_FILE}")
        events = {n: e for n, e in events.items() if n in ONLY}
    if "--check" in sys.argv:
        for e in events.values():
            hook = hook_for(e)
            log(f"{e['name']}: {e['title']!r}, voice group {e['group']!r}, {len(e['slots'])} slot(s), "
                f"webhook {'set' if valid_hook(hook) else 'MISSING'}")
        return 0 if events and all(valid_hook(hook_for(e)) for e in events.values()) else 1
    if not valid_hook(WEBHOOK) and not DRY:
        log("WEBHOOK_URL missing or not a Discord webhook URL; nothing to do")
        return 1
    if "--test" in sys.argv:
        post("🔧 voice-live-announce test message. Delete me.", ping=False)
        log("test message sent")
        return 0

    now = time.time() if now is None else now
    voice = load_json(VOICE_FILE)
    state = load_json(STATE_FILE) or {}
    changed = False

    for name, ev in events.items():
        hook = hook_for(ev)
        g = group_data(voice, ev["group"], now)
        players = server_players(ev["status_file"], now) if ev["status_file"] else None
        occ = occurrences(ev, now, tz)

        for start, key in occ:
            skey = f"{name}:{key}"
            st = state.get(skey)
            live = is_live(start, ev, g, now)
            cap_end = start + ev["cap"] * MIN

            if live and not st:
                if g["count"] < ev["min_voice"]:
                    continue                       # wait for more people
                if any(v.get("group") == name and v.get("status") == "live" for v in state.values()):
                    continue                       # overlapping slots: one post at a time
                try:
                    msg_id = post(live_text(ev, g, players, start, ping=True), ping=True, hook=hook)
                except (urllib.error.URLError, OSError, ValueError) as e:
                    log(f"{skey}: post failed ({e}); will retry next run")
                    continue
                state[skey] = {"group": name, "status": "live", "msg": msg_id, "start": start,
                               "posted_at": now, "last_seen": now, "peak": g["count"],
                               "count": g["count"], "edited_at": now}
                log(f"{skey}: announced live with {g['count']} in voice")
                changed = True

            elif live and st and st.get("status") == "live":
                st["last_seen"] = g["last"] or now      # last time anyone was in voice
                st["peak"] = max(st["peak"], g["count"])
                if g["count"] > 0 and g["count"] != st["count"] and now - st["edited_at"] >= UPDATE_MIN * MIN:
                    try:
                        edit(st["msg"], live_text(ev, g, players, start, ping=False), hook)
                        st["count"], st["edited_at"] = g["count"], now
                    except (urllib.error.URLError, OSError, ValueError) as e:
                        log(f"{skey}: count edit failed ({e})")
                changed = True

            elif st and st.get("status") == "live" and not live:
                # Ended: voice data says it's over, or data is gone and the hard cap passed.
                if g is None and now < cap_end:
                    continue                       # data old for now: don't guess
                nxt = next((s for s, _ in occ if s > now), None)
                try:
                    edit(st["msg"], ended_text(ev, st, nxt), hook)
                except (urllib.error.URLError, OSError, ValueError) as e:
                    log(f"{skey}: end edit failed ({e}); will retry next run")
                    if now < cap_end + 30 * MIN:
                        continue
                st["status"] = "ended"
                st["ended_at"] = now
                log(f"{skey}: marked ended (peak {st['peak']})")
                changed = True

    # Forget sessions older than 3 days.
    for k in [k for k, v in state.items() if now - v.get("start", 0) > 3 * 86400]:
        del state[k]
        changed = True
    if changed:
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(run())
