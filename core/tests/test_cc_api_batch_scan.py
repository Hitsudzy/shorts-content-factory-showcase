#!/usr/bin/env python3
"""CC-0041: reads never wait for the scan of the open batches; writes always
scan afresh; a dry run takes no write lock; `new` is reserved; a create
carries the wizard's position.

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_channels.py` (a temp git repository with `reel` and
`demo`). `factory.open_batches` - live: one scan of the whole `pipeline/`,
36-55 s under load - is replaced by a stand-in held on an `Event`, so "a read
did not wait" is proved by the read coming back while the scan is still held,
never by a stopwatch: nothing here is timing-sensitive under load. Every wait
has a generous ceiling (`LONG`) only so that a bug fails instead of hanging.

What is pinned:

* the first read of a root waits for the one scan; after it, a read whose
  result is past `BATCH_TTL` answers the last known result at once with its
  time (`checked_at`, `age_s`) and `checking: true`, and starts one refresh -
  however many reads come meanwhile, one scan runs;
* a failed refresh keeps the last result; a failed first scan is an error;
* a save, a create, a revert scan afresh and refuse on a batch the reads'
  result did not show yet (create: any batch; save / revert: this channel's
  or a rebuild);
* a dry run (`POST /api/channels` `dry_run`) and `POST .../check` answer while
  a write holds `_WRITE`; a real create waits for it;
* `new` (the center's `/channels/new`, the wizard) is not a channel id;
* `stance_text` on a create: the position written in the same one commit,
  checked as a PUT checks it; a bad one refused, nothing written.
"""
import json
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from api import channels as ch                        # noqa: E402
from api import factory                               # noqa: E402
from test_cc_api_channels import (                    # noqa: E402
    H, _save, client, factory_tree, files_of, git, head)

LONG = 60.0                    # a ceiling against a hang, never the measure of a check
NEW = {"channel_id": "history", "display_name": "ExampleHistory"}


class Scan:
    """A stand-in `factory.open_batches`: returns `rows`, held while `gate` is clear."""
    def __init__(self):
        self.calls = 0
        self.rows = []
        self.fail = False
        self.gate = threading.Event()
        self.gate.set()
        self.entered = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, root):
        with self._lock:
            self.calls += 1
        self.entered.set()
        assert self.gate.wait(LONG), "the stand-in scan was never released"
        if self.fail:
            raise RuntimeError("the stand-in scan broke")
        return [dict(r) for r in self.rows]


@contextmanager
def stand_in(ttl=0.0, wait=0.0):
    scan = Scan()
    saved = factory.open_batches, ch.BATCH_TTL, ch.BATCH_WAIT
    factory.open_batches, ch.BATCH_TTL, ch.BATCH_WAIT = scan, ttl, wait
    try:
        yield scan
    finally:
        scan.gate.set()
        factory.open_batches, ch.BATCH_TTL, ch.BATCH_WAIT = saved


def batch(chan=None, rebuild=False):
    return {"dir": f"/x/pipeline/{'rebuilds' if rebuild else chan}/2026-10-10T0900Z",
            "channel": None if rebuild else chan, "rebuild": rebuild, "last": None}


def in_thread(fn):
    out = {}

    def run():
        try:
            out["r"] = fn()
        except BaseException as e:                       # noqa: BLE001
            out["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


def result(t, out):
    t.join(LONG)
    assert not t.is_alive(), "the request did not come back"
    if "e" in out:
        raise out["e"]
    return out["r"]


def settle(root):
    """Wait (bounded) until no refresh of `root` is going."""
    st = ch._SCANS[str(Path(root).resolve())]
    end = time.monotonic() + LONG
    while st.running and time.monotonic() < end:
        time.sleep(0.01)
    assert not st.running


# --------------------------------------------------------------------- reads

def test_the_first_read_waits_once_then_a_read_never_waits():
    root = factory_tree()
    c = client(root)
    with stand_in(ttl=0.0, wait=0.0) as scan:
        scan.gate.clear()
        t, out = in_thread(lambda: c.get("/api/channels/template"))
        assert scan.entered.wait(LONG)
        assert t.is_alive()                     # nothing known yet: it waits for the scan
        scan.gate.set()
        r = result(t, out)
        assert r.status_code == 200, r.text
        lk = r.json()["lock"]
        assert lk["locked"] is False and lk["checked_at"].endswith("Z")
        assert isinstance(lk["age_s"], float) and lk["age_s"] >= 0
        settle(root)
        # the result is past its TTL (0): a read answers it at once while the
        # refresh it started is held - a batch the held scan would show is not
        # in the answer yet, and the answer says a check is going
        scan.gate.clear()
        scan.rows = [batch("reel")]
        r = result(*in_thread(lambda: c.get("/api/channels/reel")))
        assert r.status_code == 200, r.text
        lk = r.json()["lock"]
        assert lk["locked"] is False and lk["checking"] is True, lk
        for call in (lambda: c.get("/api/channels/template"),
                     lambda: c.get("/api/channels"),
                     lambda: c.get("/api/channels/demo"),
                     lambda: c.post("/api/channels", headers=H, json=dict(NEW, dry_run=True))):
            r = result(*in_thread(call))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("checking", body.get("lock", {}).get("checking")) is True, body
        assert scan.calls == 2, scan.calls      # the first scan and one refresh, not five
        scan.gate.set()
        settle(root)
        lk = c.get("/api/channels/reel").json()["lock"]   # the refresh landed
        assert lk["locked"] is True and lk["batches"][0]["channel"] == "reel", lk


def test_a_read_may_wait_for_its_refresh_up_to_batch_wait():
    root = factory_tree()
    c = client(root)
    with stand_in(ttl=0.0, wait=LONG) as scan:
        assert c.get("/api/channels/reel").json()["lock"]["locked"] is False
        scan.rows = [batch(rebuild=True)]
        lk = c.get("/api/channels/reel").json()["lock"]
        assert lk["locked"] is True and lk["checking"] is False, lk


def test_a_fresh_result_is_reused_within_its_ttl():
    root = factory_tree()
    c = client(root)
    with stand_in(ttl=3600.0) as scan:
        c.get("/api/channels/reel")
        c.get("/api/channels")
        c.get("/api/channels/template")
        c.post("/api/channels", headers=H, json=dict(NEW, dry_run=True))
        assert scan.calls == 1, scan.calls


def test_a_failed_refresh_keeps_the_last_result_a_failed_first_scan_is_an_error():
    root = factory_tree()
    c = client(root)
    with stand_in(ttl=0.0, wait=LONG) as scan:
        assert c.get("/api/channels/reel").status_code == 200
        scan.fail = True
        r = c.get("/api/channels/reel")
        assert r.status_code == 200 and r.json()["lock"]["locked"] is False, r.text
    other = factory_tree()
    c2 = client(other)
    with stand_in() as scan:
        scan.fail = True
        try:
            r = c2.get("/api/channels/template")
        except RuntimeError as e:               # the test client re-raises the server's error
            assert "broke" in str(e)
        else:
            assert r.status_code == 500, r.text


# --------------------------------------------------------------------- writes

def test_a_write_scans_afresh_whatever_the_reads_saw():
    root = factory_tree()
    c = client(root)
    with stand_in(ttl=3600.0) as scan:          # the reads' result never goes stale
        edit = _save(c, root, '"en"', '"de"')   # no batch: saved
        scan.rows = [batch("reel")]
        assert c.get("/api/channels/demo").json()["lock"]["locked"] is False   # cached
        start = head(root)
        d = c.get("/api/channels/reel").json()
        r = c.put("/api/channels/reel", headers=H,
                  json={"base": d["revision"], "config_text": d["config_text"].replace(
                      '"de"', '"fr"', 1)})
        assert r.status_code == 409 and r.json()["code"] == "batch_running", r.text
        scan.rows = [batch("demo")]             # another channel's batch: any blocks a create
        r = c.post("/api/channels", headers=H, json=NEW)
        assert r.status_code == 409 and r.json()["code"] == "batch_running", r.text
        scan.rows = [batch(rebuild=True)]
        r = c.post(f"/api/channels/reel/history/{edit['commit']}/revert", headers=H)
        assert r.status_code == 409 and r.json()["code"] == "batch_running", r.text
        assert head(root) == start
        assert c.get("/api/channels/reel").json()["lock"]["locked"] is True  # a write's scan is kept
        scan.rows = [batch("demo")]             # not reel's: the PUT rules stay as they were
        r = c.post(f"/api/channels/reel/history/{edit['commit']}/revert", headers=H)
        assert r.status_code == 200, r.text


def test_a_dry_run_and_a_check_take_no_write_lock():
    root = factory_tree()
    c = client(root)
    with stand_in():
        c.get("/api/channels/template")
        d = c.get("/api/channels/reel").json()
        assert ch._WRITE.acquire(timeout=LONG)  # a save or a create is going
        try:
            r = result(*in_thread(lambda: c.post("/api/channels", headers=H,
                                                 json=dict(NEW, dry_run=True))))
            assert r.status_code == 200 and r.json()["ok"], r.text
            r = result(*in_thread(lambda: c.post("/api/channels/reel/check", headers=H,
                                                 json={"config_text": d["config_text"]})))
            assert r.status_code == 200 and r.json()["ok"], r.text
            t, out = in_thread(lambda: c.post("/api/channels", headers=H, json=NEW))
            t.join(0.3)
            assert t.is_alive()                 # a real create waits for the write lock
        finally:
            ch._WRITE.release()
        r = result(t, out)
        assert r.status_code == 200 and r.json()["commit"], r.text


# --------------------------------------------------------------------- a new channel

def test_new_is_not_a_channel_id():
    assert "new" in ch.RESERVED_IDS and "template" in ch.RESERVED_IDS
    root = factory_tree()
    c = client(root)
    with stand_in():
        start = head(root)
        r = c.post("/api/channels", headers=H,
                   json={"channel_id": "new", "display_name": "New", "dry_run": True})
        d = r.json()
        assert r.status_code == 200 and d["ok"] is False and d["files"] == [], r.text
        assert [e["field"] for e in d["errors"]] == ["channel_id"], d["errors"]
        r = c.post("/api/channels", headers=H, json={"channel_id": "new", "display_name": "New"})
        assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
        assert head(root) == start and not (root / "channels" / "new.json").exists()
        assert c.get("/api/channels/new").status_code == 404


def _wizard_stance(c, thesis):
    """What the wizard sends: the dry run's position file with its thesis filled."""
    d = c.post("/api/channels", headers=H, json=dict(NEW, dry_run=True)).json()
    text = next(f["text"] for f in d["files"] if f["path"].endswith("/stance.json"))
    doc = json.loads(text)
    doc["position"]["thesis"] = thesis
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def test_a_create_carries_the_wizard_s_position_in_one_commit():
    root = factory_tree()
    c = client(root)
    with stand_in():
        text = _wizard_stance(c, "Один факт в день - и почему он важен.")
        dry = c.post("/api/channels", headers=H,
                     json=dict(NEW, stance_text=text, dry_run=True)).json()
        assert dry["ok"], dry
        assert [f["text"] for f in dry["files"] if f["path"].endswith("/stance.json")] == [text]
        start = head(root)
        r = c.post("/api/channels", headers=H, json=dict(NEW, stance_text=text))
        assert r.status_code == 200, r.text
        made = r.json()
        assert git(root, "rev-parse", "HEAD~1") == start          # one commit
        assert sorted(files_of(root)) == sorted(f["path"] for f in made["files"])
        assert (root / "channels" / "history" / "stance.json").read_text(encoding="utf-8") == text
        assert made["channel"]["stance"]["position"]["thesis"].startswith("Один факт")
        assert made["channel"]["errors"] == []
        assert "Cc-Action: create" in git(root, "log", "-1", "--format=%B")


def test_a_bad_position_on_create_is_refused_and_writes_nothing():
    root = factory_tree()
    c = client(root)
    with stand_in():
        good = json.loads(_wizard_stance(c, "x"))
        start = head(root)
        for text, field in (("{not json", "stance"),
                            ("[1, 2]", "stance"),
                            (json.dumps(dict(good, channel_id="reel")), "stance.channel_id")):
            d = c.post("/api/channels", headers=H,
                       json=dict(NEW, stance_text=text, dry_run=True)).json()
            assert d["ok"] is False and [e["field"] for e in d["errors"]] == [field], (text, d)
            r = c.post("/api/channels", headers=H, json=dict(NEW, stance_text=text))
            assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
        assert head(root) == start and not (root / "channels" / "history.json").exists()


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
