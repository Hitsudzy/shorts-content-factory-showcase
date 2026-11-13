#!/usr/bin/env python3
"""CC-0064: the publication side of the command center's API, read only
(`api/publish.py`; `GET /api/publish`, `/publish/holds`, `/publish/api-upload`,
`/publish/{channel}/queue|pause|api-upload|rotation|config|studio`,
`/publish/{channel}/notes/{slug}`) over the factory's own readers -
`publish_queue`, `channel_pause`, `publish_card`, `studio_fields`,
`upload_records`, `api_switch`, `publication_hold`, `rotate`.

In-process (starlette's TestClient) against a stand-in factory root in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`: a git repository with
`reel`, which has a slot, and `demo`, a stub without one). **Nothing outside
the temp dir is read or written**: the clock is fixed, the publisher's `.env`
and environment are stand-ins (the token and the client secret are temp paths
that do not exist - no live token is read), the tick's timer is a stand-in,
the rotation's channel config is read from the temp root; no network.

What is pinned:

* the contract: the ten reading routes, every one a GET only, version 0.48.0,
  `PublishProblem` on the problems; the writes of CC-0065 are POSTs only
  (`tests/test_cc_api_publish_writes.py`);
* nothing reads and writes at once: `api/publish.py` names each writer of
  CC-0065 only in the one function that calls it (`set_pause` in
  `pause_set`, ..., `plan_slot` - read only, but the queue's planner - in
  `_place_check`), `build` only with `claims=False` and no asker, and none of
  the other writers, model askers, notifications or the upload anywhere;
  every GET leaves the temp tree byte for byte as it was -
  `studio_fields.prepare` included;
* the queue: the slot as `slot_config` reads it, the slots taken by a placed
  card and by a journal row, the next free slot past the lead, `_queue/`,
  tomorrow's line and code, the occupants with their sources; a channel with
  no slot says so; a broken slot block is 409 `queue_broken` with the
  factory's line; a former id is the channel; an unknown channel 404;
* the pause: free / paused / expired with the factory's Russian line, the open
  row and the history; a registry that does not read is 409
  `pause_unreadable` with the factory's fail-closed line - and the queue says
  paused;
* the holds: the open ones (unresolved, unsigned) and every row, of one channel
  or all; no ledger is an empty answer; a broken one is `problem`, nothing open;
* the API-upload switch: off by default with the factory's line, on from the
  state file, a stub's line, the warnings (Testing, the timer, the token);
* the rotation: `distribution_report` of the temp root's ledger and batches; a
  channel with no `patterns.rotation` 409 `rotation_broken`;
* the publisher block (`channel_config`) and its refusal; the Studio streak
  over the journal, a broken journal 409 `journal_unreadable`;
* a placed card: the factory's short view, the form, the Studio fields of a
  ready accepted card; without the acceptance `studio: null` and the
  factory's refusal; its batch and the videos' routes; `_reserve` is a folder a
  note is read from (CF-0919); a bad day, an unknown
  slug, a note through an undeclared symlink out - 404 `unknown_note`.
"""
import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import TMP, _w, client, factory_tree     # noqa: E402
from test_cc_api_videos import make_batch                          # noqa: E402

import api                                                         # noqa: E402
from api import factory, publish                                   # noqa: E402

NOW = "2026-10-06T12:00:00+03:00"
DAY = "2026-10-08"
BATCH = "2026-10-05T0900Z"
SLUG = "paper-dragon"
TITLE = "Paper Dragon Took Ten Years #shorts"
DESCRIPTION = ("Why it took ten years.\n\nThe fact in this video comes from: Wikipedia · "
               "https://en.wikipedia.org/wiki/X\n\n#PaperDragon #shorts")
TAGS = ["paper dragon", "film", "box office"]
SETTINGS = ("Не для детей. Язык: английский. ИИ/синтетический контент: нет. Прямой рекламы нет. "
            "Снять «Автоматическое объяснение понятий».")
ROUTES = {"/api/publish", "/api/publish/holds", "/api/publish/holds/released",   # CC-0169
          "/api/publish/api-upload",
          "/api/publish/{channel}/queue", "/api/publish/{channel}/pause",
          "/api/publish/{channel}/api-upload", "/api/publish/{channel}/rotation",
          "/api/publish/{channel}/config", "/api/publish/{channel}/studio",
          "/api/publish/{channel}/notes/{slug}"}
#: What `api/publish.py` never names: the writers it does not call, the model
#: askers, the notifications and the upload of the modules it reads (CC-0065:
#: the holds' writers - `write_ledger`, `resolve_rights_only` (CC-0070: the
#: signature is `sign_hold`, in WRITERS); CC-0066:
#: the API-upload switch, the upload and the Studio record are
#: `api/publish_net.py`'s, walked by `tests/test_cc_api_publish_net.py`).
FORBIDDEN = {"set_switch", "record", "write_ledger", "resolve_rights_only", "merge", "ask_draft",
             "check_note", "tomorrow_notify", "notify_upload", "notify_accept", "send",
             "notify_bus", "_notify_bus", "upload", "apply_moves", "edited", "record_studio",
             "record_published", "record_and_commit", "write_text", "write_bytes", "unlink",
             "mkdir", "rename", "rmtree", "_write", "subprocess", "write_note", "asker"}
#: CC-0065: each writer the center calls, named only in its one function.
WRITERS = {"set_pause": "pause_set", "clear_pause": "pause_clear", "place": "card_place",
           "build": "card_build", "plan_slot": "_place_check", "assign": "rotation_assign",
           "reject": "rotation_reject", "refuse": "rotation_refuse",
           # CC-0070: the hold's signature - the one write on the ledger
           "sign_hold": "hold_sign"}

_N = [0]


def _secrets():
    _N[0] += 1
    return TMP / f"secrets-{_N[0]}"            # outside every git tree; never created


def setup():
    """The factory's injection points: the clock, a stand-in `.env` and
    environment (temp secret paths), the tick's timer."""
    s = _secrets()
    publish.FACTORY_KW.clear()
    publish.FACTORY_KW.update({
        "now": NOW, "env_file": str(s / "publisher.env"),
        "environ": {"PUBLISHER_TOKEN_FILE": str(s / "token.json"),
                    "PUBLISHER_CLIENT_SECRET_FILE": str(s / "client_secret.json"),
                    "PUBLISHER_OAUTH_MODE": "testing"},
        "timer": {"installed": False, "line": "таймер тика не установлен (подставной)"}})


def note_claims():
    return factory.collect().card().note_claims


def card_text(slug=SLUG, batch=BATCH, status="ready", publish_line=None):
    """A placed card as publish_card.py writes it: the claim block and the
    marker carry the fingerprint of this title and description, and the
    «Батч» line names the batch."""
    body = (f"# {slug} — карточка публикации\n\nБатч `pipeline/reel/{batch}`\n\n"
            f"## Название\n{TITLE}\n\n## Описание\n{DESCRIPTION}\n")
    fp = note_claims().fingerprint(body)
    claims = json.dumps({"rule": "CF-0555", "fingerprint": fp, "checked_at": "2026-10-06T09:00:00Z",
                         "batch": batch, "script_id": f"t-{slug}-script1", "claims": 2,
                         "struck": []}, ensure_ascii=False)
    mark = json.dumps({"rule": "CF-0017", "status": status, "channel": "reel", "slug": slug,
                       "batch": f"pipeline/reel/{batch}", "script_id": f"t-{slug}-script1",
                       "topic_id": f"t-{slug}", "problems": [], "fingerprint": fp},
                      ensure_ascii=False, sort_keys=True)
    when = publish_line or f"**{DAY} 01:00 МСК** — ближайший свободный слот канала"
    return (body + f"\n## Утверждения\n<!-- note_claims {claims} -->\nПроверено машиной.\n"
            f"\n## Теги\n{', '.join(TAGS)}\n\n## Публикация\n{when}\n\n## Настройки\n- {SETTINGS}\n"
            f"\n## Карточка\nСтатус: **готова**\n<!-- publish_card {mark} -->\n")


def acceptance(slug, batch=BATCH, day=DAY):
    return {"entry_id": f"reel/{batch}/{slug}", "channel": "reel", "batch_id": batch,
            "slug": slug, "topic_id": f"t-{slug}", "verdict": "accepted",
            "answered_at": "2026-10-06T08:00:00Z",
            "publish_path": f"publish/reel/{day}/{slug}.mp4"}


def studio_row(slug, day, vid, recorded, edited=False):
    return {"channel": "reel", "slug": slug, "video_id": vid, "source": "studio",
            "publish_at": f"{day}T01:00:00+03:00", "publish_day": day,
            "recorded_at": recorded, "user_edited": edited, "entry_id": f"reel/X/{slug}"}


def world():
    """reel: a placed accepted card on DAY, a journal row on the 7th, one
    video in `_queue/`, the batch the card names."""
    root = factory_tree()
    pub = root / "publish"
    d = pub / "reel" / DAY
    d.mkdir(parents=True)
    (d / f"{SLUG}.md").write_text(card_text(), encoding="utf-8")
    (d / f"{SLUG}.mp4").write_bytes(b"\0")
    q = pub / "reel" / "_queue"
    q.mkdir(parents=True)
    (q / "night-owl.md").write_text(card_text("night-owl", publish_line="Слот не назначен."),
                                    encoding="utf-8")
    _w(pub / "acceptance-log.json", {"acceptances": [acceptance(SLUG)]})
    _w(pub / "uploads.json", {"uploads": [
        studio_row("old-one", "2026-10-07", "AbCdEfGhIj0", "2026-10-05T10:00:00Z", edited=True),
        studio_row("delver", "2026-10-07", "ZyXwVuTsRq9", "2026-10-05T11:00:00Z")]})
    make_batch(root, "reel", BATCH, (SLUG,))
    return root


def files(root):
    """Every file of the tree and its bytes (git's own objects aside)."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def get(root, path, **params):
    r = client(root).get(path, params=params)
    return r.status_code, r.json()


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_publication_routes_get_only():
    spec = client(factory_tree()).get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    # the GETs of other modules with problems of their own: the копилка (CC-0122,
    # api/publish_stash.py), the card from the center (CC-0127, api/card_center.py)
    other = {"/api/publish/{channel}/stash", "/api/publish/{channel}/cards/{slug}",
             "/api/publish/{channel}/cards/build/{run_id}"}
    paths = {p: set(v) for p, v in spec["paths"].items() if p.startswith("/api/publish")
             and p not in other}
    assert all(set(spec["paths"][p]) == {"get"} for p in other), other
    reads = {p for p, m in paths.items() if "get" in m}
    assert reads == ROUTES, reads ^ ROUTES
    assert all(paths[p] == {"get"} for p in ROUTES), paths
    assert all(m == {"post"} for p, m in paths.items() if p not in ROUTES), paths   # CC-0065
    for p in ROUTES:
        for status in ("404", "409", "500"):
            ref = spec["paths"][p]["get"]["responses"][status]["content"]["application/json"]
            assert ref["schema"]["$ref"].endswith("/PublishProblem"), (p, status)
    codes = set(spec["components"]["schemas"]["PublishProblem"]["properties"]["code"]["enum"])
    assert {"unknown_channel", "unknown_note", "queue_broken", "pause_unreadable"} <= codes


def _names(node):
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} | \
        {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | \
        {a.name.split(".")[0] for n in ast.walk(node) if isinstance(n, (ast.Import, ast.ImportFrom))
         for a in n.names}


def test_the_module_names_no_writer_asker_or_notification():
    tree = ast.parse((ROOT / "api" / "publish.py").read_text(encoding="utf-8"))
    hit = _names(tree) & FORBIDDEN
    assert not hit, hit
    # CC-0065: a writer only in its one (top-level) function, nowhere else
    where = {}
    for node in tree.body:
        for w in _names(node) & set(WRITERS):
            where.setdefault(w, set()).add(getattr(node, "name", type(node).__name__))
    assert where == {w: {f} for w, f in WRITERS.items()}, where
    # the build: from the given draft, claims=False, no asker - the model is never asked
    builds = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "build"]
    assert len(builds) == 1, builds
    kw = {k.arg: k.value for k in builds[0].keywords}
    assert isinstance(kw.get("claims"), ast.Constant) and kw["claims"].value is False, kw
    assert "draft" in kw and "asker" not in kw and "jobs" not in kw, kw
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)}
    assert "open" not in calls and "open" not in _names(tree), "publish.py opens a file itself"


def test_every_route_leaves_the_tree_as_it_was():
    setup()
    root = world()
    before = files(root)
    c = client(root)
    for path in ("/api/publish", "/api/publish/holds", "/api/publish/holds/released",
                 "/api/publish/api-upload",
                 "/api/publish/reel/queue", "/api/publish/reel/pause",
                 "/api/publish/reel/api-upload", "/api/publish/reel/config",
                 "/api/publish/reel/studio", f"/api/publish/reel/notes/{SLUG}",
                 "/api/publish/reel/notes/night-owl", "/api/publish/demo/queue"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.text)
    assert files(root) == before


# --------------------------------------------------------------------- the queue
def test_the_queue_is_the_factory_s():
    setup()
    root = world()
    code, q = get(root, "/api/publish/reel/queue", days=5)
    assert code == 200, q
    assert q["slot"] == {"channel": "reel", "times": ["01:00"], "tz": "Europe/Moscow",
                         "per_day": 1, "lead_hours": 2.0}, q["slot"]
    taken = {s["day"]: s["taken_by"] for s in q["slots"]}
    assert taken == {"2026-10-06": None, "2026-10-07": "delver", DAY: SLUG,
                     "2026-10-09": None, "2026-10-10": None}, taken
    assert q["slots"][1]["label"] == "2026-10-07 01:00 МСК"
    assert q["slots"][1]["at"] == "2026-10-06T22:00:00Z", q["slots"][1]
    # 01:00 of the 6th is past: the nearest free slot past the lead is the 9th
    assert q["next_free"]["day"] == "2026-10-09" and q["next_free"]["label"] == \
        "2026-10-09 01:00 МСК", q["next_free"]
    assert [s["day"] for s in q["slots"] if s["next_free"]] == ["2026-10-09"]
    assert q["waiting"] == ["night-owl"], q["waiting"]
    assert q["paused"] is None and q["pause_notices"] == []
    assert q["tomorrow"]["state"] == "ok" and q["tomorrow"]["code"] == 0, q["tomorrow"]
    assert "delver" in q["tomorrow"]["line"]
    occ = {o["slug"]: o["sources"] for o in q["occupants"]}
    assert occ["delver"] == ["uploads.json:ZyXwVuTsRq9"], occ
    assert occ[SLUG] == [f"publish/reel/{DAY}/"], occ
    assert q["journal"] == "publish/uploads.json" and q["as_of"] == "2026-10-06T09:00:00Z"
    # a former id is the channel; an unknown one is 404
    code, old = get(root, "/api/publish/old-reel/queue", days=5)
    assert code == 200 and old["channel"] == "reel", old
    code, bad = get(root, "/api/publish/nope/queue")
    assert code == 404 and bad["code"] == "unknown_channel", bad
    code, bad = get(root, "/api/publish/reel/queue", days=0)
    assert code == 422, bad


def test_a_channel_without_a_slot_says_so_and_a_broken_slot_is_the_factory_s_line():
    setup()
    root = world()
    code, q = get(root, "/api/publish/demo/queue")
    assert code == 200, q
    assert q["slot"] is None and q["slots"] == [] and q["next_free"] is None, q
    assert q["tomorrow"]["state"] == "error" and "no publisher.slot" in q["tomorrow"]["line"]
    code, ov = get(root, "/api/publish")
    assert code == 200 and [c["channel"] for c in ov["channels"]] == ["reel"], ov
    assert ov["channels"][0]["next_free"]["day"] == "2026-10-09" and \
        ov["channels"][0]["error"] is None
    cfg = json.loads((root / "channels" / "reel.json").read_text(encoding="utf-8"))
    cfg["publisher"]["slot"] = {"time": "25:00", "tz": "Europe/Moscow"}
    _w(root / "channels" / "reel.json", cfg)
    code, bad = get(root, "/api/publish/reel/queue")
    assert code == 409 and bad["code"] == "queue_broken", bad
    assert "is not HH:MM" in bad["message"], bad
    code, ov = get(root, "/api/publish")
    assert code == 200 and "is not HH:MM" in ov["channels"][0]["error"], ov


# --------------------------------------------------------------------- the pause
def test_the_pause_is_the_factory_s_and_the_queue_sees_it():
    setup()
    root = world()
    code, p = get(root, "/api/publish/reel/pause")
    assert code == 200 and p["state"] == "free", p
    assert "паузы нет" in p["line"] and p["open_row"] is None and p["history"] == []
    old = {"pause_id": "reel/2026-10-01T00:00:00Z", "channel": "reel", "by": "user",
           "reason": "старая", "set_at": "2026-10-01T00:00:00Z", "until": None,
           "cleared_at": "2026-10-02T00:00:00Z", "cleared_by": "user", "clear_note": None}
    now = {"pause_id": "reel/2026-10-05T00:00:00Z", "channel": "old-reel", "by": "monitor",
           "reason": "нарушение", "set_at": "2026-10-05T00:00:00Z", "until": None,
           "cleared_at": None, "cleared_by": None, "clear_note": None}
    _w(root / "publish" / "channel-pauses.json", {"pauses": [old, now]})
    code, p = get(root, "/api/publish/reel/pause")
    assert code == 200 and p["state"] == "paused", p
    assert "НА ПАУЗЕ" in p["line"] and "нарушение" in p["line"], p["line"]
    assert p["open_row"]["pause_id"] == now["pause_id"] and len(p["history"]) == 2
    code, q = get(root, "/api/publish/reel/queue")
    assert code == 200 and q["tomorrow"]["state"] == "paused" and "нарушение" in q["paused"], q
    now["until"] = "2026-10-06T00:00:00+03:00"
    _w(root / "publish" / "channel-pauses.json", {"pauses": [old, now]})
    code, p = get(root, "/api/publish/reel/pause")
    assert code == 200 and p["state"] == "expired" and "ИСТЕКЛА" in p["line"], p
    code, q = get(root, "/api/publish/reel/queue")
    assert q["paused"] is None and q["pause_notices"] and "ИСТЕКЛА" in q["pause_notices"][0]
    (root / "publish" / "channel-pauses.json").write_text("{not json", encoding="utf-8")
    code, bad = get(root, "/api/publish/reel/pause")
    assert code == 409 and bad["code"] == "pause_unreadable", bad
    assert "реестр пауз нечитаем" in bad["message"], bad
    code, q = get(root, "/api/publish/reel/queue")
    assert code == 200 and "реестр пауз нечитаем" in q["paused"], q


# --------------------------------------------------------------------- the holds
def hold(hid, channel="reel", **kw):
    return dict({"hold_id": hid, "channel": channel, "batch_id": BATCH, "topic_id": hid,
                 "verdict": "review", "reason_code": "compliance_review_hold",
                 "reason": "review", "resolved_at": None, "signature": None}, **kw)


def test_the_holds_are_the_ledger_s():
    setup()
    root = world()
    code, h = get(root, "/api/publish/holds")
    assert code == 200 and h["exists"] is False and h["open"] == [] and h["rows"] == [], h
    _w(root / "publish" / "publication-holds.json", {"holds": [
        hold("t-open"), hold("t-done", resolved_at="2026-10-02T00:00:00Z"),
        hold("t-signed", signature={"user": "user", "date": "2026-10-03", "note": "ok"}),
        hold("t-other", channel="demo"), hold("t-old", channel="old-reel")]})
    code, h = get(root, "/api/publish/holds", channel="reel")
    assert code == 200 and h["channel"] == "reel" and h["problem"] is None, h
    assert [r["hold_id"] for r in h["open"]] == ["t-open", "t-old"], h["open"]
    assert [r["hold_id"] for r in h["rows"]] == ["t-open", "t-done", "t-signed", "t-old"]
    code, h = get(root, "/api/publish/holds")
    assert {r["hold_id"] for r in h["open"]} == {"t-open", "t-other", "t-old"} and \
        len(h["rows"]) == 5, h
    (root / "publish" / "publication-holds.json").write_text("[", encoding="utf-8")
    code, h = get(root, "/api/publish/holds")
    assert code == 200 and h["problem"] and "could not be read" in h["problem"], h
    assert h["open"] == [] and h["rows"] == []


# --------------------------------------------------------------------- the API upload
def test_the_api_upload_switch_and_its_warnings():
    setup()
    root = world()
    code, a = get(root, "/api/publish/api-upload")
    assert code == 200 and a["path"] == "schedule/api-upload.json", a
    st = {s["channel"]: s for s in a["channels"]}
    assert set(st) == {"reel", "demo"} and not st["reel"]["on"], st
    assert "ВЫКЛЮЧЕНА" in st["reel"]["line"] and "грузить нечего" in st["demo"]["line"], st
    w = " | ".join(a["warnings"])
    assert "Testing" in w and "подставной" in w and "нет токена" in w, a["warnings"]
    _w(root / "schedule" / "api-upload.json", {
        "channels": {"reel": {"on": True, "at": "2026-10-05T00:00:00Z", "by": "user",
                              "note": "после аудита"}},
        "history": [{"at": "2026-10-05T00:00:00Z", "by": "user", "channel": "reel",
                     "action": "enable", "note": "после аудита", "task": "CF-0607",
                     "warnings": ["w1"]}]})
    code, a = get(root, "/api/publish/reel/api-upload")
    assert code == 200 and a["channel"] == "reel" and len(a["channels"]) == 1, a
    s = a["channels"][0]
    assert s["on"] is True and "ВКЛЮЧЕНА" in s["line"] and s["warnings"] == ["w1"], s
    assert s["history"][0]["action"] == "enable"


# --------------------------------------------------------------------- the rotation
def test_the_rotation_report_is_rotate_s():
    setup()
    root = world()
    rt = factory.rotate()
    for cid, rot in (("reel", {"no_repeat_window_k": 1, "distribution_window": 3}),
                     ("demo", None)):
        cfg = json.loads((root / "channels" / f"{cid}.json").read_text(encoding="utf-8"))
        cfg["patterns"] = {"allowed_pattern_ids": [], **({"rotation": rot} if rot else {})}
        _w(root / "channels" / f"{cid}.json", cfg)
    real = rt.load_channel
    rt.load_channel = lambda ch: json.loads(
        (root / "channels" / f"{rt.resolve_channel(ch)}.json").read_text(encoding="utf-8"))
    try:
        code, r = get(root, "/api/publish/reel/rotation")
        code_demo, bad = get(root, "/api/publish/demo/rotation")
    finally:
        rt.load_channel = real
    assert code == 200 and r["ledger"] == "rotation/ledger", r
    rep = r["report"]
    assert rep["channel"] == "reel" and rep["k_configured"] == 1 and rep["window"] == 3, rep
    assert rep["eligible_pairs"] == [] and rep["assignments_total"] == 0, rep
    assert rep["awaiting_material"] == [], rep
    assert code_demo == 409 and bad["code"] == "rotation_broken", bad
    assert "patterns.rotation is missing" in bad["message"], bad


# --------------------------------------------------------------------- the publisher block, Studio
def test_the_publisher_block_and_its_refusal():
    setup()
    root = world()
    code, c = get(root, "/api/publish/reel/config")
    assert code == 200 and c["ok"] is False and "must be a string with" in c["error"], c
    pc = factory.collect().card()
    cfg = json.loads((root / "channels" / "reel.json").read_text(encoding="utf-8"))
    cfg["publisher"].update({key: " ".join(fields) for key, fields in pc.REQUIRED_TEMPLATES})
    cfg["publisher"].update({"hashtags": {"min": 1, "max": 3}, "settings": ["Не для детей."]})
    _w(root / "channels" / "reel.json", cfg)
    code, c = get(root, "/api/publish/reel/config")
    assert code == 200 and c["ok"] is True and c["error"] is None, c
    assert c["publisher"]["slot"]["time"] == "01:00" and c["publisher"]["hashtags"]["max"] == 3


def test_the_studio_streak_is_the_journal_s():
    setup()
    root = world()
    code, s = get(root, "/api/publish/reel/studio")
    assert code == 200 and s["journal_exists"] is True and s["rows"] == 2, s
    assert s["streak"]["streak"] == 1 and s["streak"]["goal"] == 5 and \
        s["streak"]["run"] == ["delver"], s
    assert s["streak"]["last_edited"]["slug"] == "old-one", s
    (root / "publish" / "uploads.json").write_text("{", encoding="utf-8")
    code, bad = get(root, "/api/publish/reel/studio")
    assert code == 409 and bad["code"] == "journal_unreadable", bad
    code, bad = get(root, "/api/publish/reel/queue")
    assert code == 409 and bad["code"] == "queue_broken", bad
    (root / "publish" / "uploads.json").unlink()
    code, s = get(root, "/api/publish/reel/studio")
    assert code == 200 and s["journal_exists"] is False and s["streak"]["streak"] == 0, s
    assert s["rows"] == 0, s


def test_the_studio_rows_count_only_this_channel_s():
    """CC-0149: `rows` - the journal's rows naming the channel; 0 with no
    journal, 0 with other channels' rows only, else their count."""
    setup()
    root = world()
    jpath = root / "publish" / "uploads.json"
    jpath.unlink()
    code, s = get(root, "/api/publish/reel/studio")
    assert code == 200 and s["journal_exists"] is False and s["rows"] == 0, s
    other = [dict(studio_row(f"o-{i}", "2026-10-07", f"OtHeRvId{i:03d}", f"2026-10-05T1{i}:00:00Z"),
                  channel="tech", entry_id=f"tech/X/o-{i}") for i in range(3)]
    _w(jpath, {"uploads": other})
    code, s = get(root, "/api/publish/reel/studio")
    assert code == 200 and s["journal_exists"] is True and s["rows"] == 0, s
    assert s["streak"]["studio_videos"] == 0, s
    mine = [studio_row("a-one", "2026-10-07", "AaAaAaAaAa1", "2026-10-05T10:00:00Z"),
            dict(studio_row("b-two", "2026-10-08", "BbBbBbBbBb2", "2026-10-06T10:00:00Z"),
                 source="api")]
    _w(jpath, {"uploads": other + mine})
    code, s = get(root, "/api/publish/reel/studio")
    assert code == 200 and s["rows"] == 2 and s["streak"]["studio_videos"] == 1, s


# --------------------------------------------------------------------- a placed card
def test_a_placed_card_its_view_form_and_studio_fields():
    setup()
    root = world()
    code, n = get(root, f"/api/publish/reel/notes/{SLUG}")
    assert code == 200, n
    assert n["day"] == DAY and n["path"] == f"publish/reel/{DAY}/{SLUG}.md", n
    assert n["ready"] is True and n["why"] is None and n["title"] == TITLE, n
    assert n["view"].startswith(f"Карточка `{SLUG}` — готова"), n["view"]
    assert n["form"]["made_for_kids"]["value"] is False and n["ask_user"] == [], n["form"]
    st = n["studio"]
    assert n["studio_refusal"] is None and st, n["studio_refusal"]
    assert st["title"] == TITLE and st["tags"] == TAGS and st["entry_id"] == f"reel/{BATCH}/{SLUG}"
    assert st["schedule"]["msk_day"] == DAY and st["schedule"]["time"] == "01:00", st["schedule"]
    b = n["batch"]
    assert b["path"] == f"reel/{BATCH}" and b["error"] is None, b
    assert b["script_id"] == f"t-{SLUG}-script1" and b["topic_id"] == f"t-{SLUG}", b
    assert b["card_url"] == f"/api/batches/reel/{BATCH}/videos/{SLUG}/card", b
    r = client(root).get(b["card_url"])
    assert r.status_code == 200 and r.json()["slug"] == SLUG, r.text
    # the one in _queue/: no acceptance -> no Studio fields, the factory's refusal
    code, w = get(root, "/api/publish/reel/notes/night-owl", day="_queue")
    assert code == 200 and w["day"] == "_queue" and w["studio"] is None, w
    assert w["studio_refusal"] and w["form"]["language"]["value"] == "английский", w
    assert w["batch"]["error"], w["batch"]


def test_a_note_of_the_reserve_reads_with_its_day():
    """CC-0181 (CF-0919): a withdrawn video's note is in `_reserve/`."""
    setup()
    root = world()
    res = root / "publish" / "reel" / "_reserve"
    res.mkdir(parents=True)
    (res / "night-owl.md").write_text(card_text("night-owl", publish_line="Слот не назначен."),
                                      encoding="utf-8")
    code, n = get(root, "/api/publish/reel/notes/night-owl", day="_reserve")
    assert code == 200, n
    assert n["day"] == "_reserve" and n["path"] == "publish/reel/_reserve/night-owl.md", n
    assert n["studio"] is None and n["studio_refusal"], n
    # two places, neither in the journal: the day is asked for, and the reserve is named
    code, bad = get(root, "/api/publish/reel/notes/night-owl")
    assert code == 404 and bad["code"] == "unknown_note" and "_reserve" in bad["message"], bad
    code, bad = get(root, f"/api/publish/reel/notes/{SLUG}", day="_reserve")
    assert code == 404 and bad["code"] == "unknown_note", bad
    code, bad = get(root, "/api/publish/reel/notes/night-owl", day="_elsewhere")
    assert code == 404 and bad["code"] == "unknown_note" and "_reserve" in bad["message"], bad


def test_a_note_that_is_not_there_or_leads_out_is_404():
    setup()
    root = world()
    for slug, params in (("no-such", {}), (SLUG, {"day": "2026-13-45"}),
                         (SLUG, {"day": "yesterday"}), (SLUG, {"day": "2026-10-09"})):
        code, bad = get(root, f"/api/publish/reel/notes/{slug}", **params)
        assert code == 404 and bad["code"] == "unknown_note", (slug, params, bad)
    out = TMP / f"outside-{_N[0]}"
    out.mkdir()
    (out / "stray.md").write_text(card_text("stray"), encoding="utf-8")
    (root / "publish" / "reel" / "2026-10-09").symlink_to(out, target_is_directory=True)
    code, bad = get(root, "/api/publish/reel/notes/stray")
    assert code == 404 and bad["code"] == "unknown_note", bad
    assert "leads out of publish/" in bad["message"], bad      # found by locate, refused here


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    publish.FACTORY_KW.clear()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
