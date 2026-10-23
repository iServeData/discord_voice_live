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


# ---------------------------------------------------------------- shared schedule file
def split_docs(tmp, status_file):
    """The same events as events_doc(), split into a shared schedule file and server settings."""
    full = events_doc(status_file)
    sched = {"timezone": full.pop("timezone"), "events": {}}
    for name, e in full["events"].items():
        sched["events"][name] = {k: e.pop(k) for k in list(e) if k != "server_status_file"}
        sched["events"][name]["calendar"] = {"note": "extra keys for a website are ignored"}
    (tmp / "schedule.json").write_text(json.dumps(sched))
    full["schedule_file"] = str(tmp / "schedule.json")
    return full, sched


def test_schedule_file_gives_the_same_posts(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    people = lambda t: [A1, A1, A2] if hours(t)[0] == 5 and 9.8 <= hours(t)[1] < 10.5 else []  # noqa: E731
    plain = Sim(a).run(at(2026, 10, 17, 9, 0), 3 * 60, people)
    doc, _ = split_docs(b, str(b / "status.json"))
    shared = Sim(b, doc=doc).run(at(2026, 10, 17, 9, 0), 3 * 60, people)
    assert plain and [(m, c) for m, _, c in plain] == [(m, c) for m, _, c in shared]


def test_schedule_file_change_moves_the_session(tmp_path):
    doc, sched = split_docs(tmp_path, str(tmp_path / "status.json"))
    sched["events"]["tactical"]["slots"] = [{"days": ["thu"], "time": "19:00"}]
    (tmp_path / "schedule.json").write_text(json.dumps(sched))
    s = Sim(tmp_path, doc=doc)
    thu = lambda t: [A1, A2] if hours(t)[0] == 3 and 19 <= hours(t)[1] < 19.5 else []  # noqa: E731
    calls = s.run(at(2026, 10, 22, 18, 0), 3 * 60, thu)
    assert [c[0] for c in calls][:1] == ["POST"] and "Tactical night is live" in calls[0][2]
    sat = lambda t: [A1, A2] if hours(t)[0] == 5 and 10 <= hours(t)[1] < 10.5 else []  # noqa: E731
    (tmp_path / "state").rename(tmp_path / "state_thu")
    assert Sim(tmp_path, doc=doc).run(at(2026, 10, 24, 9, 30), 90, sat) == []   # the old Saturday slot is gone


@pytest.mark.parametrize("change, message", [
    (lambda d, s: d["events"]["tactical"].update(slots=[{"days": ["sat"], "time": "09:00"}]), "set here and in"),
    (lambda d, s: d.update(timezone="UTC"), "timezone is set here and in"),
    (lambda d, s: d["events"].update(other={}), "no event 'other'"),
    (lambda d, s: d.update(schedule_file="schedule.json"), "absolute path"),
    (lambda d, s: s["events"]["tactical"].update(seed_goal="20"), "seed_goal"),
])
def test_schedule_file_problems_are_reported(tmp_path, change, message):
    doc, sched = split_docs(tmp_path, None)
    change(doc, sched)
    (tmp_path / "schedule.json").write_text(json.dumps(sched))
    (tmp_path / "events.json").write_text(json.dumps(doc))
    s = Sim(tmp_path, doc=doc)
    with pytest.raises(s.m.ConfigError, match=message):
        s.m.load_events(str(tmp_path / "events.json"))


def test_schedule_event_can_be_renamed_and_check_says_where(tmp_path, capsys):
    doc, sched = split_docs(tmp_path, None)
    doc["events"] = {"seeds": {"schedule_event": "tactical", "voice_group": "tactical"}}
    sched["events"]["tactical"].pop("voice_group", None)
    (tmp_path / "schedule.json").write_text(json.dumps(sched))
    s = Sim(tmp_path, doc=doc)
    tz, events = s.m.load_events(str(tmp_path / "events.json"))
    assert list(events) == ["seeds"] and events["seeds"]["slots"][0][1:] == (18, 15)
    sys.argv = ["x", "--check"]
    try:
        assert s.m.run() == 0
    finally:
        sys.argv = ["x"]
    out = capsys.readouterr().out
    assert "sat/sun/mon/tue/wed/thu 18:15, sat 10:00 (America/Los_Angeles)" in out and "(tactical)" in out
