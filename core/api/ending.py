"""CC-0101: a channel's ending clip (`channels/<channel>/ending.mp4`) and the
generator that draws it from the brand (`scripts/brand_ending.py`, CF-0565) -
what the center can honestly offer: **a read**, no launch.

`GET /api/channels/{channel}/ending` - only through the factory's own
functions:

    end_card.ending_path(cfg, root, cfg_path)  where the clip is and by which
                                               route (`video_editor.ending.path`
                                               - config - or the convention)
    end_card.ending_seconds(cfg)               the length the channel declares
                                               (`narration_budget.ending_seconds`)
    end_card.probe_ending(path)                what ffprobe says: seconds, size,
                                               fps, an audio track
    end_card.check_ending(probe, declared, ...)  the Video Editor's own check,
                                               against the format brand_ending
                                               renders (its W x H at FPS - the
                                               composition's, its docstring says)
    brand_ending.BRANDS, W, H, FPS, FRAMES     the channels it can draw and how

They run in a child interpreter (`run_reader`, a seam of the tests): the
Video Editor's scripts put their folder on `sys.path` and import their
neighbours (`common`, `rhythm`, `meme_layer`, `_runlog`) the plain way - not
names to plant in the center's own process. The child's cwd is a temp dir
and `RUNLOG_BATCH` is not passed, so the probe (`runlog.run_child`) writes
into no batch's journal. The file's bytes, mtime and sha256 are read here. The child takes a few
seconds (the Video Editor's imports, ffprobe): its answer is kept per state
of the channel's config, the clip and the two scripts (`cached`).

**The render (CC-0114, on CF-0722).** The factory keeps a render's
arguments as channel data now: `channels/<c>/brand.json` -> `ending`
(`clip`, `clip_sha256`, `render`: null - made by hand, ExampleFilm - or
`{fonts, track, track_sha256, audio_start, audio_gain_db}`), read by
`shared/channel_data.py` (`brand`, `ending`, `ending_errors`, `EndingError`
with its `code`). The same child reads the section and asks
`brand_ending.render_plan(channel, root=)` - what `brand_ending.py <c>
--plan` prints, nothing rendered: the plan, or a refusal with its code
(`ending_file_missing`, `ending_sha256_mismatch`, `ending_invalid`,
`ending_args_missing`, `ending_no_generator`). `render.available` is the
plan's ok; a refusal is said in Russian (`REFUSALS`), its code in its own
field, the factory's line behind «подробнее». The fonts and the tracks are not
in the tree yet, so science and tech answer `ending_file_missing` honestly.

`POST /api/channels/{channel}/ending/plan` - the same read afresh, the open
batches of the channel (`channels.lock`, fresh - a batch or a rebuild reads
the clip), a render of the channel this API started and not finished; a
confirm token (action `ending_render`, CONFIRM_TTL s, single use) when all
say yes. `POST /api/channels/{channel}/ending {confirm}` - the token spent,
all of it again, the plan's fingerprint the same, then `brand_ending.py
<c>` with the plan's own values as flags (the same ffmpeg command, byte for
byte - CF-0722's promise) started detached through `api/child.py`
(`child.detach`: the factory's own detached start, the log
`schedule/logs/<day>-<c>-ending.log`); the answer is the pid and the log,
at once. The center never waits on it nor signals it.

CC-0156: the render commits the clip when it ends with 0 - the argv handed to
`child.detach` is `api/detached_commit.py` before `brand_ending.py`'s own
(`_launch`; the answer's `argv` stays the script's): it runs the script in
its process, then one commit of what moved of `channels/<c>/ending.mp4`,
`Cc-Channel: <c>` / `Cc-Action: ending_render` (`api/root_commit.py`). A
render that failed commits nothing; git's refusal is said in the render's
log (`cc-commit: refused ...`), the clip stays in the tree, nothing staged.
`_running` reads the render's own last line past those `cc-commit:` lines.

There is no media URL: no route of the center serves a channel's own files
(the batch videos and the memes have theirs), so `media_url` is null.

Every refusal is a `BatchFault` (`{message, code, details}`), every answer
goes out through `api/paths.clean`.
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import batches, channels, child, detached_commit, factory, paths
from .batches import BatchFault, _channel, _digest, _issue, _spend
from .settings import CODE

SCRIPT = "scripts/brand_ending.py"
VE_SCRIPTS = "agents/video-editor/scripts"
CHANNEL_DATA = "shared/channel_data.py"
BRAND_FILE = "brand.json"
FONT_FILES = ("Poppins-ExtraBold.ttf", "Poppins-Bold.ttf")
READ_TIMEOUT_S = 30
SOURCES_DOCS = ("SOURCES.md", "beds/SOURCES.md")
_CACHE = {}                 # (root, channel) -> (key, the child's answer)
_CACHE_LOCK = threading.Lock()

#: The confirm action of a render (batches' token store).
ACTION = "ending_render"
batches.register_actions({ACTION: ("план рендера концовки", "рендер не запущен",
                                   "рендера концовки канала")})
#: brand_ending.py's own deadline (RENDER_DEADLINE_SECONDS): a render this API
#: started is taken as running for so long unless its log says it ended.
RENDER_WINDOW_S = 600.0
_RENDER = threading.Lock()  # one confirm at a time
_STARTED = {}               # (root, channel) -> {pid, log, out, at (monotonic), started_at}
_clock = time.monotonic     # the tests turn it

#: The arguments of a render (`brand_ending.main`) and where the channel's data
#: keeps them (`channels/<c>/brand.json` -> `ending.render`, CF-0722).
NEEDS = [
    {"arg": "--fonts", "key": "ending.render.fonts", "required": True, "path": True,
     "what": "каталог с Poppins-ExtraBold.ttf и Poppins-Bold.ttf"},
    {"arg": "--audio", "key": "ending.render.track", "required": True, "path": True,
     "what": "скачанный CC0-трек целиком (проверяется по ending.render.track_sha256)"},
    {"arg": "--audio-start", "key": "ending.render.audio_start", "required": True,
     "path": False, "what": "с какой секунды трека, с"},
    {"arg": "--audio-gain-db", "key": "ending.render.audio_gain_db", "required": False,
     "path": False, "what": "поправка громкости, дБ (нет - 0.0)"},
]

#: A refusal's code -> (HTTP status of a confirm, the Russian line; {brand} is
#: the channel's brand.json from the root). The factory's codes and the
#: center's own (by_hand, batch_open, render_running, plan_broken).
REFUSALS = {
    "ending_by_hand": (409, "Концовка канала {channel} сделана вручную - рендер не нужен: в {brand} "
                            "раздел ending.render пустой, записаны только ролик и его sha256."),
    "ending_no_generator": (409, "brand_ending.py не рисует концовку этого канала - в его "
                                 "списке брендов канала нет, рендер из центра невозможен."),
    "ending_file_missing": (409, "Рендер не запустить: файлов для него нет в дереве - шрифтов "
                                 "Poppins и/или трека по путям из {brand} (ending.render). "
                                 "Положите их туда - и план откроется."),
    "ending_sha256_mismatch": (409, "Рендер не запустить: трек в дереве - не тот файл, что "
                                    "записан в {brand} (sha256 не совпадает). Подменённый "
                                    "файл не используется; если замена намеренная, запишите "
                                    "новый sha256 в {brand} и SOURCES.md канала."),
    "ending_invalid": (422, "Раздел ending в {brand} не проходит проверку фабрики - рендер не "
                            "запустить; исправьте строки из подробностей."),
    "ending_args_missing": (409, "Рендеру не хватает аргументов: в {brand} (ending.render) "
                                 "записано не всё - нужны шрифты, трек с его sha256 и "
                                 "audio_start."),
    "batch_open": (409, "{lock} Рендер концовки подождёт - её ролик читает батч."),
    "render_running": (409, "Концовка канала уже рендерится (запущена из центра {ago} с "
                            "назад) - дождитесь конца, лог: {log}."),
    "plan_broken": (500, "План рендера не прочитан - brand_ending.py ответил ошибкой; "
                         "подробности ниже."),
}
#: What the factory should do so that a refusal goes away (null: nothing of the factory's).
FACTORY_ASK = {
    "ending_file_missing": "Файлов нет в дереве: положить шрифты Poppins (ExtraBold и Bold) "
                           "и трек концовки по путям из {brand} - трек с тем sha256, что "
                           "там записан.",
    "ending_sha256_mismatch": "Вернуть записанный трек или записать sha256 нового в {brand} "
                              "и SOURCES.md канала.",
    "ending_invalid": "Исправить раздел ending в {brand} по строкам проверки.",
    "ending_args_missing": "Дописать в {brand} ending.render: fonts, track, track_sha256, "
                           "audio_start.",
}

# The child's program: the factory's functions, one JSON line out.
_CHILD = r"""
import importlib.util, json, sys
from pathlib import Path
root, cfg_path, ve_dir, be_path, cd_path, cid = sys.argv[1:7]
out = {"path": None, "source": None, "path_error": None, "declared": None, "probe": None,
       "probe_error": None, "check_error": None, "brand": None, "brand_error": None,
       "data": None, "plan": None}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, ve_dir)
import end_card
cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
try:
    p, src = end_card.ending_path(cfg, root, cfg_path)
    out["path"], out["source"] = (str(p) if p else None), src
except end_card.EndCardError as e:
    out["path_error"] = str(e)
    p = None
out["declared"] = end_card.ending_seconds(cfg)
fmt = None
be = None
try:
    be = load("brand_ending", be_path)
    fmt = {"width": be.W, "height": be.H, "fps": be.FPS}
    out["brand"] = {"channels": sorted(be.BRANDS), "width": be.W, "height": be.H, "fps": be.FPS,
                    "frames": be.FRAMES, "motifs": {k: v.get("motif") for k, v in be.BRANDS.items()}}
except Exception as e:
    out["brand_error"] = f"{type(e).__name__}: {e}"
data = {"exists": False, "section": None, "errors": [], "error": None}
try:
    cd = load("channel_data_for_the_center", cd_path)
    try:
        doc = cd.brand(cid, root)
        data["exists"] = doc is not None
        if doc is not None and "ending" in doc:
            data["errors"] = list(cd.ending_errors(doc["ending"]))
        data["section"] = cd.ending(cid, root)
    except cd.EndingError as e:
        data["error"] = {"code": e.code, "line": str(e)}
except Exception as e:
    data["error"] = {"code": "plan_broken", "line": f"{type(e).__name__}: {e}"}
out["data"] = data
if be is not None:
    try:
        out["plan"] = {"ok": True, "plan": be.render_plan(cid, root=Path(root)), "refusal": None}
    except Exception as e:
        code = getattr(e, "code", None) if type(e).__name__ == "EndingRefused" else None
        out["plan"] = {"ok": False, "plan": None,
                       "refusal": {"code": code or "plan_broken",
                                   "message": str(e) if code else f"{type(e).__name__}: {e}"}}
if p is not None:
    try:
        out["probe"] = end_card.probe_ending(p)
    except Exception as e:
        out["probe_error"] = str(e)
if out["probe"] is not None and fmt is not None:
    try:
        end_card.check_ending(out["probe"], out["declared"], {"output": fmt}, p)
    except end_card.EndCardError as e:
        out["check_error"] = str(e)
print(json.dumps(out))
"""


def run_reader(cmd, cwd, env):
    """The child, run (`child.run`, bounded by READ_TIMEOUT_S): (returncode,
    stdout, stderr). A seam of the tests."""
    return child.run(cmd, cwd=cwd, env=env, timeout=READ_TIMEOUT_S)


def run_launcher(argv, root, day, label, env):
    """The render started detached (`child.detach`): (pid, log). A seam of the
    tests - nothing is ever rendered by them."""
    return child.detach(argv, root=root, day=day, label=label, env=env)


def _env():
    return {k: v for k, v in os.environ.items() if k != "RUNLOG_BATCH"}


def _read(root, cid):
    cfg = Path(root).resolve() / factory.CHANNELS_SUBDIR / f"{cid}.json"
    cmd = [sys.executable, "-c", _CHILD, str(Path(root).resolve()), str(cfg),
           str(CODE / VE_SCRIPTS), str(CODE / SCRIPT), str(CODE / CHANNEL_DATA), cid]
    with tempfile.TemporaryDirectory(prefix="cc-api-ending-") as tmp:
        try:
            rc, out, err = run_reader(cmd, tmp, _env())
        except child.Timeout:
            raise BatchFault(500, "factory_broken", "Концовка канала не прочитана: фабрика не "
                                                    "ответила вовремя.",
                             [f"end_card reader: no answer in {READ_TIMEOUT_S} s"]) from None
        except OSError as e:
            raise BatchFault(500, "factory_broken", "Концовка канала не прочитана.",
                             [f"end_card reader did not start: {e}"]) from e
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    try:
        if rc != 0 or not lines:
            raise ValueError(f"exit {rc}")
        return json.loads(lines[-1])
    except ValueError as e:
        tail = [ln for ln in (err or "").splitlines() if ln.strip()][-3:]
        raise BatchFault(500, "factory_broken", "Концовка канала не прочитана: фабрика "
                                                "ответила ошибкой.",
                         [f"end_card reader: {e}", *tail]) from None


def _file(p):
    try:
        st = p.stat()
    except OSError:
        return {"exists": False, "bytes": None, "mtime": None, "sha256": None}
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return {"exists": True, "bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sha256": h.hexdigest()}


def _stat(p):
    try:
        st = Path(p).stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def _section(got):
    return ((got or {}).get("data") or {}).get("section")


def _render_files(base, got):
    """The files a render names in the channel's data (the fonts, the track)."""
    render = (_section(got) or {}).get("render") or {}
    out = []
    if isinstance(render.get("fonts"), str):
        out += [base / render["fonts"] / f for f in FONT_FILES]
    if isinstance(render.get("track"), str):
        out.append(base / render["track"])
    return out


def _key(root, cid, got=None):
    """What the child's answer depends on: the channel's config and its
    brand.json, the clip it named (or the convention's), the files the data
    names for a render, the three scripts."""
    base = Path(root).resolve()
    clip = (got or {}).get("path") or base / factory.CHANNELS_SUBDIR / cid / "ending.mp4"
    return (str(base), cid, _stat(base / factory.CHANNELS_SUBDIR / f"{cid}.json"),
            _stat(base / factory.CHANNELS_SUBDIR / cid / BRAND_FILE), str(clip), _stat(clip),
            tuple((str(f), _stat(f)) for f in _render_files(base, got)),
            _stat(CODE / SCRIPT), _stat(CODE / VE_SCRIPTS / "end_card.py"),
            _stat(CODE / CHANNEL_DATA))


def _keep(root, cid, got):
    with _CACHE_LOCK:
        _CACHE[(str(Path(root).resolve()), cid)] = (_key(root, cid, got), got)


def _cached_read(root, cid):
    with _CACHE_LOCK:
        hit = _CACHE.get((str(Path(root).resolve()), cid))
    if hit is not None and _key(root, cid, hit[1]) == hit[0]:
        return hit[1], True
    got = _read(root, cid)
    _keep(root, cid, got)
    return got, False


def _brand_rel(cid):
    return f"{factory.CHANNELS_SUBDIR}/{cid}/{BRAND_FILE}"


def _refusal(cid, code, line=None, **fmt):
    """{code, message (Russian, no code in it), details} of a refusal."""
    _status, text = REFUSALS.get(code, REFUSALS["plan_broken"])
    return {"code": code, "message": text.format(brand=_brand_rel(cid), channel=cid, **fmt),
            "details": [f"{code}: {line}"] if line else [code]}


def _factory_refusal(cid, got):
    """The refusal of a render as the factory decides it - the section's own
    error, a section made by hand, the plan's refusal - or None."""
    data = got.get("data") or {}
    section = data.get("section")
    if data.get("error"):
        e = data["error"]
        r = _refusal(cid, e.get("code") or "plan_broken", e.get("line"))
        r["details"] += [f"ending_errors: {x}" for x in data.get("errors") or []]
        return r
    if section is not None and section.get("render") is None:
        return _refusal(cid, "ending_by_hand",
                        f"{_brand_rel(cid)}: ending.render is null (made by hand)")
    plan = got.get("plan")
    if plan is None:
        return _refusal(cid, "plan_broken", got.get("brand_error") or "brand_ending.py did not "
                                                                     "load")
    if not plan.get("ok"):
        ref = plan.get("refusal") or {}
        return _refusal(cid, ref.get("code") or "plan_broken", ref.get("message"))
    return None


def _running(root, cid):
    """A render of the channel this API started and not over: {pid, log, out,
    ago_s} or None. Over: the window passed, or the log's last line is the
    clip (brand_ending's own end), an ffmpeg failure, a refusal or a
    traceback."""
    with _CACHE_LOCK:
        run = _STARTED.get((str(Path(root).resolve()), cid))
    if run is None:
        return None
    ago = _clock() - run["at"]
    if ago >= RENDER_WINDOW_S:
        return None
    try:
        text = Path(run["log"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    tail = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.startswith(detached_commit.PREFIX)]
    if tail and (tail[-1] == str(run["out"]) or "ffmpeg failed" in tail[-1]
                 or tail[-1].startswith("ending_") or "Traceback" in text):
        return None
    return dict(run, ago_s=round(ago, 1))


def _commit_refused(root, log):
    """CC-0161: the last `cc-commit:` line of the render's log, when it says
    `refused` - the rest of it (paths cut); else None."""
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    said = [ln.strip()[len(detached_commit.PREFIX):].strip() for ln in text.splitlines()
            if ln.strip().startswith(detached_commit.PREFIX)]
    if not said or not said[-1].startswith("refused"):
        return None
    rest = said[-1][len("refused"):].strip()
    rest = rest[1:].strip() if rest.startswith("-") else rest
    return paths.clean(rest or "refused", root)


def _last_run(root, cid):
    with _CACHE_LOCK:
        run = _STARTED.get((str(Path(root).resolve()), cid))
    if run is None:
        return None
    return {"pid": run["pid"], "log": paths.rel(root, run["log"]),
            "started_at": run["started_at"], "running": _running(root, cid) is not None,
            "commit_refused": _commit_refused(root, run["log"])}


def _plan_view(plan):
    if not plan:
        return None
    return {k: plan.get(k) for k in ("fonts", "audio", "audio_start", "audio_gain_db", "out",
                                     "command", "sources", "clip_sha256")}


def _needs(root, section):
    render = (section or {}).get("render") or {}
    out = []
    for n in NEEDS:
        field = n["key"].rsplit(".", 1)[1]
        value = render.get(field)
        present = None
        if n["path"] and isinstance(value, str):
            q = Path(root) / value
            present = (all((q / f).is_file() for f in FONT_FILES) if field == "fonts"
                       else q.is_file())
        out.append({"arg": n["arg"], "key": n["key"], "required": n["required"],
                    "stored": field in render, "value": value, "present": present,
                    "what": n["what"]})
    return out


def _render_block(root, cid, got):
    refusal = _factory_refusal(cid, got)
    plan = (got.get("plan") or {}).get("plan") if refusal is None else None
    section = _section(got)
    docs = []
    for rel in SOURCES_DOCS:
        d = Path(root) / factory.CHANNELS_SUBDIR / cid / rel
        try:
            if "brand_ending.py" in d.read_text(encoding="utf-8"):
                docs.append(paths.rel(root, d))
        except OSError:
            pass
    ask = FACTORY_ASK.get((refusal or {}).get("code"))
    return {"available": refusal is None, "why": refusal["message"] if refusal else None,
            "refusal": refusal, "by_hand": section is not None and section.get("render") is None,
            "plan": _plan_view(plan), "needs": _needs(root, section), "sources_docs": docs,
            "factory_ask": ask.format(brand=_brand_rel(cid)) if ask else None,
            "last_run": _last_run(root, cid)}


def _data_block(root, cid, got, clip_file):
    data = got.get("data") or {}
    section = data.get("section")
    clip = (section or {}).get("clip")
    want = (section or {}).get("clip_sha256")
    matches = None
    if want:
        f = clip_file(Path(root) / clip) if clip else None
        matches = None if not f or not f["exists"] else f["sha256"] == want
    err = data.get("error")
    return {"path": _brand_rel(cid), "exists": bool(data.get("exists")),
            "section": section is not None, "clip": clip, "clip_sha256": want,
            "clip_matches": matches,
            "render": (section or {}).get("render"), "note": (section or {}).get("note"),
            "errors": list(data.get("errors") or []),
            "error": {"code": err.get("code"), "line": err.get("line")} if err else None}


def view(root, channel):
    """The channel's ending clip as the factory sees it, its data
    (brand.json's `ending`) and whether the center can render it (the
    factory's plan). Kept per state of the config, brand.json, the clip, the
    render's files and the scripts (`cached`)."""
    cid = _channel(root, channel)
    got, cached = _cached_read(root, cid)
    root = Path(root)
    convention = root / factory.CHANNELS_SUBDIR / cid / "ending.mp4"
    path = Path(got["path"]) if got.get("path") else None
    f = _file(path) if path else {"exists": False, "bytes": None, "mtime": None,
                                  "sha256": None}
    brand = got.get("brand") or {}

    def clip_file(q):
        return f if path is not None and q.resolve() == path.resolve() else _file(q)

    probe, check_error = got.get("probe"), got.get("check_error")
    out = {"channel": cid, "cached": cached,
           "path": paths.rel(root, path) if path else paths.rel(root, convention),
           "source": got.get("source"), "path_error": got.get("path_error"), **f,
           "declared_seconds": got.get("declared"), "probe": probe,
           "probe_error": got.get("probe_error"),
           "check": None if probe is None or not brand else
           {"ok": check_error is None, "error": check_error,
            "against": {"width": brand["width"], "height": brand["height"],
                        "fps": brand["fps"]}},
           "media_url": None,
           "generator": {"script": SCRIPT, "renders_channel": cid in (brand.get("channels") or []),
                         "motif": (brand.get("motifs") or {}).get(cid),
                         "channels": brand.get("channels") or [],
                         "frames": brand.get("frames"), "fps": brand.get("fps"),
                         "error": got.get("brand_error")},
           "data": _data_block(root, cid, got, clip_file),
           "render": _render_block(root, cid, got)}
    return paths.clean(out, root)


# ---------------------------------------------------------------- the render (CC-0114)
def _check(root, cid):
    """A fresh read and every guard: (got, refusal or None, the lock)."""
    got = _read(root, cid)
    _keep(root, cid, got)
    refusal = _factory_refusal(cid, got)
    try:
        lock = channels.lock(root, cid, fresh=True)
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Не проверить, идёт ли батч канала - рендер не "
                                                "запущен.",
                         [f"open batches: {type(e).__name__}: {e}"]) from e
    if refusal is None and lock.get("locked"):
        refusal = _refusal(cid, "batch_open", "; ".join(
            str(b.get("dir")) for b in lock.get("batches") or []) or "a batch is open",
            lock=lock.get("message") or "Идёт батч канала.")
    run = _running(root, cid) if refusal is None else None
    if run is not None:
        refusal = _refusal(cid, "render_running", f"pid {run['pid']}, {run['ago_s']} s ago",
                           ago=int(run["ago_s"]), log=paths.rel(root, run["log"]))
    return got, refusal, lock


def _argv(cid, plan):
    """brand_ending.py with the plan's own values as flags - the same ffmpeg
    command, byte for byte, as the plan's (CF-0722)."""
    return [sys.executable, str(CODE / SCRIPT), cid, "--fonts", str(plan["fonts"]),
            "--audio", str(plan["audio"]), "--audio-start", repr(float(plan["audio_start"])),
            "--audio-gain-db", repr(float(plan["audio_gain_db"])), "--out", str(plan["out"])]


def _launch(root, cid, plan, argv):
    """CC-0156: what `child.detach` starts - `detached_commit` (the clip's
    commit when the render ends with 0) before the script and its flags."""
    return detached_commit.argv_head(detached_commit.ENDING, Path(root).resolve(), cid,
                                     plan["out"], argv[1]) + argv[2:]


def _fingerprint(cid, got):
    plan = (got.get("plan") or {}).get("plan") or {}
    return _digest({"channel": cid, "section": _section(got),
                    "plan": {k: plan.get(k) for k in ("fonts", "audio", "audio_start",
                                                      "audio_gain_db", "out", "command",
                                                      "sources", "clip_sha256")}})


def render_plan(root, channel):
    """{action, channel, ok, why, refusal, by_hand, plan, argv, needs, batches,
    fingerprint, confirm, expires_in_s}: the factory's plan read afresh, the
    guards, and a confirm token when nothing refuses. Nothing is rendered."""
    cid = _channel(root, channel)
    got, refusal, lock = _check(root, cid)
    block = _render_block(root, cid, got)
    plan = (got.get("plan") or {}).get("plan") if refusal is None else None
    fp = _fingerprint(cid, got)
    out = {"action": ACTION, "channel": cid, "ok": refusal is None,
           "why": refusal["message"] if refusal else None, "refusal": refusal,
           "by_hand": block["by_hand"], "plan": _plan_view(plan),
           "argv": _argv(cid, plan) if plan else None, "needs": block["needs"],
           "batches": [str(b.get("dir")) for b in lock.get("batches") or []],
           "log_dir": "schedule/logs", "fingerprint": fp, "confirm": None,
           "expires_in_s": None}
    if refusal is None:
        out.update(confirm=_issue(root, ACTION, cid, fp), expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def render(root, channel, token):
    """{ok, channel, pid, log, started_at, argv, out}: the token spent, the
    read and the guards again, the same fingerprint, then the render started
    detached - answered at once, never waited on."""
    cid = _channel(root, channel)
    if not _RENDER.acquire(blocking=False):
        raise BatchFault(409, "busy", "Идёт другой запуск рендера концовки - подождите и "
                                      "запросите план заново.", ["one ending confirm at a time"])
    try:
        tok = _spend(root, ACTION, cid, token)
        got, refusal, _lock = _check(root, cid)
        if refusal is not None:
            status = REFUSALS.get(refusal["code"], (409, ""))[0]
            raise BatchFault(status, refusal["code"], refusal["message"],
                             paths.clean(refusal["details"], root))
        if _fingerprint(cid, got) != tok["fingerprint"]:
            raise BatchFault(409, "check_changed", "План рендера изменился с момента "
                                                   "подтверждения - рендер не запущен; "
                                                   "посмотрите план заново.",
                             ["the fingerprint of the plan differs from the confirmed one"])
        plan = got["plan"]["plan"]
        argv = _argv(cid, plan)
        now = datetime.now(timezone.utc)
        try:
            pid, log = run_launcher(_launch(root, cid, plan, argv), str(Path(root).resolve()),
                                    now.strftime("%Y-%m-%d-%H%M%S"), f"{cid}-ending", _env())
        except (child.Timeout, OSError, child.Detach) as e:
            lines = getattr(e, "lines", None) or [f"{type(e).__name__}: {e}"]
            raise BatchFault(500, "start_failed", "Рендер концовки не запустился - фабрика "
                                                  "не ответила на запуск.",
                             paths.clean(list(lines), root)) from None
        started_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        with _CACHE_LOCK:
            _STARTED[(str(Path(root).resolve()), cid)] = {
                "pid": pid, "log": log, "out": plan["out"], "at": _clock(),
                "started_at": started_at}
        return paths.clean({"ok": True, "channel": cid, "pid": pid, "log": log,
                            "started_at": started_at, "argv": argv, "out": plan["out"]}, root)
    finally:
        _RENDER.release()
