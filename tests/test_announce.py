"""The announcer, driven minute by minute through simulated voice activity (no network)."""
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import discord_voice_live as col  # noqa: E402

TZ = ZoneInfo("America/Los_Angeles")
A1, A2, F = "000000000000000021", "000000000000000022", "000000000000000011"
HOOK = "https://discord.com/api/webhooks/000000000000000099/token"


def events_doc(status_file=None, **over):
    doc = {"timezone": "America/Los_Angeles", "events": {
        "tactical": {"title": "Tactical night", "slots": [
            {"days": ["sat", "sun", "mon", "tue", "wed", "thu"], "time": "18:15"}, {"days": ["sat"], "time": "10:00"}],
            "early_minutes": 15, "window_minutes": 30, "cap_minutes": 120, "channels": [A1, A2],
            "url": "https://example.org/tactical/", "seed_goal": 20, "server_status_file": status_file},
        "friday": {"title": "Friday game night", "slots": [{"days": ["fri"], "time": "19:00"}],
                   "window_minutes": 240, "cap_minutes": 420, "url": "https://example.org/friday/"}}}
    for k, v in over.items():
        doc["events"][k] = v
    return doc


class Sim:
    def __init__(self, tmp, env=None, doc=None):
        self.tmp = tmp
        self.voice, self.status = tmp / "voice.json", tmp / "status.json"
        (tmp / "events.json").write_text(json.dumps(doc or events_doc(str(self.status))))
        os.environ.update({"WEBHOOK_URL": HOOK, "VOICE_FILE": str(self.voice), "STATE_DIRECTORY": str(tmp / "state"),
                           "EVENTS_FILE": str(tmp / "events.json"), "PING_ROLE_ID": "", "ANNOUNCE_EVENTS": "",
                           "ANNOUNCE_GROUPS": "", "MIN_VOICE": "2", "FRIDAY_WEBHOOK_URL": "", **(env or {})})
        spec = importlib.util.spec_from_file_location("ann", ROOT / "voice_live_announce.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.calls, self.prev = [], {}

        def http(method, url, body=None):
            self.calls.append((method, url, body["content"]))
            return {"id": f"m{len(self.calls)}"}
        self.m.http = http
        self.groups = col.parse_groups(f"friday={F};tactical={A1},{A2}")

    def run(self, start, minutes, people, players=12, outage=()):
        for k in range(minutes):
            t = start + 60 * k
            w = None if k in outage else {"channels": [{"id": c} for c in (F, A1, A2)],
                                          "members": [{"channel_id": c} for c in people(t)]}
            self.prev = col.compute(self.groups, w, self.prev, t, 600)
            self.voice.write_text(json.dumps(self.prev))
            self.status.write_text(json.dumps({"schema_version": 1, "generated_at": col.iso(t),
                                               "community_server": {"state": "responding", "players": {
                                                   "current": players, "max": 100, "observed_at": col.iso(t)}}}))
            assert self.m.run(now=t) == 0
        return self.calls


def at(*a):
    return datetime(*a, tzinfo=TZ).timestamp()


def hours(t):
    d = datetime.fromtimestamp(t, TZ)
    return d.weekday(), d.hour + d.minute / 60


def test_one_post_then_edits_then_ended(tmp_path):
    s = Sim(tmp_path)

    def people(t):
        wd, h = hours(t)
        if wd == 5 and 9.8 <= h < 10.5:
            return [A1, A1, A2]
        if wd == 5 and 10.5 <= h < 11:
            return [A2] * 5
        return []
    calls = s.run(at(2026, 10, 17, 9, 0), 4 * 60, people)
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == HOOK + "?wait=true"
    assert posts[0][2].splitlines() == ["🟢 **Tactical night is live**", "3 in voice now · server 12/100 (seed goal: 20)",
                                        f"Hop in: <#{A1}>", f"Scheduled <t:{int(at(2026, 10, 17, 10, 0))}:t> · info: <https://example.org/tactical/>"]
    assert any(c[0] == "PATCH" and "5 in voice now" in c[2] and f"<#{A2}>" in c[2] for c in calls)  # busier channel
    ended = calls[-1][2]
    assert calls[-1][0] == "PATCH" and "session ended" in ended and "Peak 5 in voice" in ended and "Next: <t:" in ended


def test_below_min_voice_and_off_schedule_stay_quiet(tmp_path):
    s = Sim(tmp_path)

    def people(t):
        wd, h = hours(t)
        if wd == 5 and 18.1 <= h < 18.6:
            return [A1]                       # one person in the window
        if wd == 6 and 2 <= h < 3:
            return [A1, A2, A2]               # busy, but not near a scheduled start
        return []
    assert s.run(at(2026, 10, 17, 17, 0), 11 * 60, people) == []


def test_old_voice_data_never_announces(tmp_path):
    s = Sim(tmp_path)
    calls = s.run(at(2026, 10, 17, 9, 50), 20, lambda t: [A1, A2], outage=range(0, 20))
    assert calls == []


def test_disabled_event_and_filter(tmp_path):
    doc = events_doc()
    doc["events"]["friday"]["enabled"] = False
    s = Sim(tmp_path, doc=doc)
    fri = lambda t: [F, F, F] if hours(t)[0] == 4 and 19 <= hours(t)[1] < 20 else []  # noqa: E731
    assert s.run(at(2026, 10, 16, 18, 30), 120, fri) == []
    (tmp_path / "x").mkdir()
    s2 = Sim(tmp_path / "x", env={"ANNOUNCE_GROUPS": "tactical"})
    assert s2.run(at(2026, 10, 16, 18, 30), 120, fri) == []          # old setting name still works


def test_per_event_webhook_and_ping(tmp_path):
    other = "https://discord.com/api/webhooks/000000000000000098/other"
    s = Sim(tmp_path, env={"FRIDAY_WEBHOOK_URL": other, "PING_ROLE_ID": "000000000000000077"})
    fri = lambda t: [F, F] if hours(t)[0] == 4 and 19 <= hours(t)[1] < 21 else []  # noqa: E731
    calls = s.run(at(2026, 10, 16, 18, 30), 4 * 60, fri)
    assert calls[0][0] == "POST" and calls[0][1].startswith(other) and calls[0][2].startswith("<@&000000000000000077>")
    assert all(c[1].startswith(other) for c in calls)
    assert all("<@&" not in c[2] for c in calls[1:])                   # edits never ping
    assert "server" not in calls[0][2]                                   # no status file for this event


def test_wall_clock_follows_daylight_saving(tmp_path):
    s = Sim(tmp_path)
    tz, events = s.m.load_events(str(tmp_path / "events.json"))
    before = [k for st, k in s.m.occurrences(events["tactical"], at(2026, 10, 31, 12, 0), tz) if k.endswith("18:15")]
    after = dict((k, st) for st, k in s.m.occurrences(events["tactical"], at(2026, 11, 2, 12, 0), tz))
    assert "2026-10-31T18:15" in before
    assert datetime.fromtimestamp(after["2026-11-02T18:15"], TZ).hour == 18      # still 18:15 local after the change


@pytest.mark.parametrize("bad,msg", [
    ({"slots": []}, "at least one slot"),
    ({"slots": [{"days": ["someday"], "time": "18:15"}]}, "days"),
    ({"slots": [{"days": ["fri"], "time": "7pm"}]}, "HH:MM"),
    ({"slots": [{"days": ["fri"], "time": "19:00"}], "window_minutes": 300, "cap_minutes": 100}, "cap_minutes"),
    ({"slots": [{"days": ["fri"], "time": "19:00"}], "url": "ftp://x"}, "url"),
    ({"slots": [{"days": ["fri"], "time": "19:00"}], "channels": ["abc"]}, "channels"),
])
def test_events_file_is_validated(tmp_path, bad, msg):
    s = Sim(tmp_path, doc=events_doc(friday=bad))
    with pytest.raises(s.m.ConfigError, match=msg):
        s.m.load_events(str(tmp_path / "events.json"))
    assert s.m.run(now=at(2026, 10, 16, 19, 0)) == 2


def test_example_events_file_is_valid(tmp_path):
    s = Sim(tmp_path)
    tz, events = s.m.load_events(str(ROOT / "config" / "events.json.example"))
    assert list(events) == ["tactical"] and str(tz) == "America/Los_Angeles"     # friday is disabled


def test_check_mode(tmp_path, capsys, monkeypatch):
    s = Sim(tmp_path)
    monkeypatch.setattr(sys, "argv", ["x", "--check"])
    assert s.m.run() == 0
    out = capsys.readouterr().out
    assert "tactical: 'Tactical night'" in out and "webhook set" in out and HOOK not in out
