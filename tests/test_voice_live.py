import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import discord_voice_live as v

G = v.parse_groups("friday=000000000000000011;tactical=000000000000000021,000000000000000022")
CH = [{"id": "000000000000000011"}, {"id": "000000000000000021"}, {"id": "000000000000000022"}]
T0 = 1792000000.0

def w(*chans, channels=CH):
    return {"channels": channels, "members": [{"username": "x%d" % i, "id": str(i), "channel_id": c} for i, c in enumerate(chans)]
            + [{"username": "idle", "id": "99"}]}

def test_counts_and_no_names():
    d = v.compute(G, w("000000000000000011", "000000000000000021", "000000000000000022", "000000000000000022"), {}, T0, 600)
    assert d["groups"]["friday"]["count"] == 1 and d["groups"]["tactical"]["count"] == 3
    assert d["groups"]["tactical"]["channels"]["000000000000000022"] == 2
    s = json.dumps(d); assert "x0" not in s and "idle" not in s and '"99"' not in s
    assert d["groups"]["friday"]["occupied_since"] == v.iso(T0)

def test_session_survives_short_gap_and_ends_after_grace():
    d1 = v.compute(G, w("000000000000000011"), {}, T0, 600)
    d2 = v.compute(G, w(), d1, T0 + 300, 600)                       # empty 5 min
    assert d2["groups"]["friday"]["occupied_since"] == v.iso(T0)
    d3 = v.compute(G, w("000000000000000011"), d2, T0 + 540, 600)  # back within grace
    assert d3["groups"]["friday"]["occupied_since"] == v.iso(T0)
    d4 = v.compute(G, w(), d3, T0 + 540 + 601, 600)                 # empty > grace
    assert d4["groups"]["friday"]["occupied_since"] is None
    assert d4["groups"]["friday"]["last_occupied_at"] == v.iso(T0 + 540)
    d5 = v.compute(G, w("000000000000000011"), d4, T0 + 3000, 600) # new session
    assert d5["groups"]["friday"]["occupied_since"] == v.iso(T0 + 3000)

def test_fetch_failure_keeps_history_and_flags():
    d1 = v.compute(G, w("000000000000000011"), {}, T0, 600)
    d2 = v.compute(G, None, d1, T0 + 60, 600)
    assert d2["source_ok"] is False and d2["groups"]["friday"]["count"] is None
    assert d2["observed_at"] == v.iso(T0) and d2["groups"]["friday"]["occupied_since"] == v.iso(T0)

def test_unlisted_channel_flagged():
    d = v.compute(G, w(channels=CH[1:]), {}, T0, 600)
    assert d["groups"]["friday"]["listed"] is False and d["groups"]["tactical"]["listed"] is True

def test_bad_groups_rejected():
    for bad in ["", "friday=", "BAR=000000000000000011", "friday=123", "friday=000000000000000011,abc"]:
        try: v.parse_groups(bad); assert False, bad
        except ValueError: pass

def test_atomic_write(tmp_path):
    p = tmp_path / "voice.json"; v.write_atomic(str(p), {"version": 1}); assert json.loads(p.read_text()) == {"version": 1}
    assert oct(os.stat(p).st_mode & 0o777) == "0o644" and len(os.listdir(tmp_path)) == 1
