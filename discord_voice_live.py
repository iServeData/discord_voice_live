#!/usr/bin/env python3
"""Discord voice presence publisher (no bot, no token).

Part of https://github.com/iServeData/discord_voice_live

Reads the server's public Discord widget (widget.json) and writes a small public
JSON file with HEAD COUNTS ONLY per channel group, plus when each group was last
occupied. No usernames, avatars or member IDs are ever written.

Runs once per invocation (systemd timer, every 60 s). Standard library only.

Settings (environment, see /etc/discord-voice-live/voice.env):
  VOICE_GUILD_ID      Discord server ID
  VOICE_GROUPS        "name=channelId[,channelId];name=channelId"
  VOICE_OUT           output file (default /var/www/html/live/voice.json)
  VOICE_GRACE_SECONDS gap that still counts as one session (default 600 = 10 min)
"""
import calendar, json, os, re, sys, tempfile, time, urllib.request, urllib.error

MAX_BYTES = 1_000_000
UA = "discord-voice-live/1.1 (+https://github.com/iServeData/discord_voice_live)"
SNOWFLAKE = re.compile(r"^\d{17,20}$")
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def iso(ts):
    return None if ts is None else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def parse_iso(s):
    try:
        return float(calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return None


def parse_groups(spec):
    groups = {}
    for part in (spec or "").split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, ids = part.partition("=")
        name = name.strip()
        chans = [c.strip() for c in ids.split(",") if c.strip()]
        if not NAME.match(name) or not chans or not all(SNOWFLAKE.match(c) for c in chans):
            raise ValueError("bad VOICE_GROUPS entry: %r" % part)
        groups[name] = chans
    if not groups:
        raise ValueError("VOICE_GROUPS is empty")
    return groups


def fetch_widget(guild_id, timeout=10):
    url = "https://discord.com/api/guilds/%s/widget.json" % guild_id
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("widget response too large")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("members"), list):
        raise ValueError("unexpected widget format")
    return data


def load_previous(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("version") == 1 else {}
    except Exception:
        return {}


def compute(groups, widget, prev, now, grace):
    """Return the new public document. widget=None means the fetch failed."""
    prev_groups = prev.get("groups") if isinstance(prev.get("groups"), dict) else {}
    out = {"version": 1, "checked_at": iso(now), "grace_seconds": int(grace), "groups": {}}
    if widget is None:
        out["source_ok"] = False
        out["observed_at"] = prev.get("observed_at")
        for name in groups:
            g = prev_groups.get(name) or {}
            out["groups"][name] = {"listed": bool(g.get("listed")), "count": None, "channels": {},
                                   "occupied_since": g.get("occupied_since"),
                                   "last_occupied_at": g.get("last_occupied_at")}
        return out
    out["source_ok"] = True
    out["observed_at"] = iso(now)
    listed_ids = {str(c.get("id")) for c in widget.get("channels") or [] if isinstance(c, dict)}
    per_chan = {}
    for m in widget["members"]:
        if isinstance(m, dict) and m.get("channel_id"):
            cid = str(m["channel_id"])
            per_chan[cid] = per_chan.get(cid, 0) + 1
    for name, chans in groups.items():
        g = prev_groups.get(name) or {}
        since = parse_iso(g.get("occupied_since") or "")
        last = parse_iso(g.get("last_occupied_at") or "")
        listed = all(c in listed_ids for c in chans)
        counts = {c: per_chan.get(c, 0) for c in chans}
        total = sum(counts.values())
        if total > 0:
            if since is None or last is None or now - last > grace:
                since = now                     # a new session starts
            last = now
        elif since is not None and (last is None or now - last > grace):
            since = None                        # session over (empty longer than grace)
        out["groups"][name] = {"listed": listed, "count": total, "channels": counts,
                               "occupied_since": iso(since), "last_occupied_at": iso(last)}
    return out


def write_atomic(path, doc):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".voice-", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    guild = os.environ.get("VOICE_GUILD_ID", "").strip()
    if not SNOWFLAKE.match(guild):
        print("VOICE_GUILD_ID missing or invalid", file=sys.stderr)
        return 2
    groups = parse_groups(os.environ.get("VOICE_GROUPS", ""))
    out_path = os.environ.get("VOICE_OUT", "/var/www/html/live/voice.json")
    grace = float(os.environ.get("VOICE_GRACE_SECONDS", "600"))
    prev = load_previous(out_path)
    now = time.time()
    try:
        widget = fetch_widget(guild)
    except (urllib.error.URLError, ValueError, OSError, json.JSONDecodeError) as e:
        print("widget fetch failed: %s" % type(e).__name__, file=sys.stderr)
        widget = None
    doc = compute(groups, widget, prev, now, grace)
    write_atomic(out_path, doc)
    summary = ", ".join("%s=%s%s" % (n, g["count"], "" if g["listed"] else "(not listed)")
                        for n, g in doc["groups"].items())
    print(("ok " if doc["source_ok"] else "SOURCE UNAVAILABLE ") + summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
