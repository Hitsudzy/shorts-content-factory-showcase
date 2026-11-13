"""CC-0099: a batch's run summary, read only - what `scripts/runlog summary`
gives for a batch. Only through the factory's own functions
(`api/factory.py`):

    shared/runlog/summary.py   compute - the sections as data, exactly what
                               `runlog summary --json` prints (CF-0110: the
                               DoD answers, stage times, gaps, waits, the
                               operator, tokens, windows, resources, the topic
                               funnel, scores, stopcock, monitors, ...);
                               SUMMARY_FILE - RUN_SUMMARY.md
    shared/runlog/runlog.py    events_path - the batch's RUN_EVENTS.jsonl

**The answer**: `data` - `compute(<batch>)` serialized the way the CLI's
`--json` does it (`json.dumps(..., default=str)`, so a value that is not
JSON is its `str`); `file` - the batch's RUN_SUMMARY.md as `batch-done`
wrote it (its text, size, time), when it has one. Neither is an error when
missing: a batch with no RUN_EVENTS.jsonl yet has `data: null` and
`data_note` («ещё нет»), a batch not closed yet has `file: null` and
`file_note`. A `compute` that fails is `data_error` (the file, when there is
one, still answers) - the CLI would print a traceback.

**Nothing here writes**: `summary.write` (RUN_SUMMARY.md) and `summary.main`
are never named - `tests/test_cc_api_run_summary.py` walks this file's
names. `compute` reads the batch directory only (its events, its stage
files), no network.

**The cost**: `compute` reads the whole journal - ~9 s of one core on a
finished 12 MB RUN_EVENTS.jsonl. So it runs one at a time (`_LOCK`) and its
result is kept per state of the batch (the journal's and the top-level
files' mtime and size): a second read of an unchanged batch answers at once,
`cached: true`. A batch still going changes with every event, so a reader
polls it no faster than `poll_s`.

**The funnel's codes in Russian** (CC-0113, CF-0714): `data.funnel` goes out
with `reason_ru` beside every `reason_code` of its rows, and
`funnel_reasons_ru` maps every code it names (`losses`, `unknown_codes`, the
rows) to the factory's `funnel.reason_ru` - null for a code outside the
vocabulary. The kept `data` is never written: the funnel is a copy.

The paths in the answer are cut by `api/paths.clean` in the route.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import factory
from .batches import PIPELINE_DIR, batch_dir

SUMMARY_FILE = "RUN_SUMMARY.md"       # = summary.SUMMARY_FILE
#: The recommended poll interval of a batch going, seconds.
POLL_S = 60
_KEEP = 4
_KEPT = {}                            # str(batch dir) -> (state, computed_at, data)
_LOCK = threading.Lock()              # one compute at a time - the machine's sake

NO_EVENTS = ("Событий прогона (RUN_EVENTS.jsonl) ещё нет - сводке не из чего считаться: "
             "она появится с первым маркером батча.")
NO_FILE = "RUN_SUMMARY.md ещё нет: его пишет batch-done, когда батч закрыт."


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(d, events):
    """What the summary is computed from: the journal and the batch's top-level
    files (its stage JSONs) - their mtime and size."""
    out = []
    for p in [events, *sorted(d.iterdir())]:
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            out.append((p.name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def _file(root, d):
    """The batch's RUN_SUMMARY.md - only a file inside the batch (a symlink out
    is not read: `factory.contained`, as the logs)."""
    p = factory.contained(root, PIPELINE_DIR, d.parent.name, d.name, SUMMARY_FILE)
    if p is None or not p.is_file():
        return None
    st = p.stat()
    return {"name": SUMMARY_FILE, "size": st.st_size, "modified": _iso(st.st_mtime),
            "text": p.read_text(encoding="utf-8", errors="replace")}


def _data(d):
    """(data, data_note, data_error, computed_at, cached)."""
    rl, sm = factory.runlog(), factory.run_summary()
    events = Path(rl.events_path(d))
    if not events.is_file():
        return None, NO_EVENTS, None, None, False
    with _LOCK:
        state = _state(d, events)
        kept = _KEPT.get(str(d))
        if kept and kept[0] == state:
            return kept[2], None, None, kept[1], True
        try:
            data = json.loads(json.dumps(sm.compute(d), ensure_ascii=False, default=str))
        except Exception as e:                                  # noqa: BLE001
            return None, None, f"runlog summary не посчиталась: {type(e).__name__}: {e}", \
                None, False
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _KEPT.pop(str(d), None)
        _KEPT[str(d)] = (state, at, data)
        while len(_KEPT) > _KEEP:
            _KEPT.pop(next(iter(_KEPT)))
        return data, None, None, at, False


def summary(root, channel, batch_id):
    d = batch_dir(root, channel, batch_id)
    f = _file(root, d)
    data, note, err, at, cached = _data(d)
    fun, codes = None, {}
    if isinstance(data, dict) and isinstance(data.get("funnel"), dict):
        # CC-0113 (CF-0714): `reason_ru` beside every `reason_code` of the
        # funnel and the map of every code it names - the kept data untouched
        fun = factory.with_reason_ru(data["funnel"])
        data = dict(data, funnel=fun)
        codes = factory.reasons_ru(_funnel_codes(fun))
    return {"batch": f"{channel}/{batch_id}", "channel": channel, "batch_id": batch_id,
            "file": f, "file_note": None if f else NO_FILE,
            "data": data, "data_note": note, "data_error": err,
            "computed_at": at, "cached": cached, "poll_s": POLL_S,
            "funnel_reasons_ru": codes}


def _funnel_codes(f):
    """Every code the funnel names: `losses` keys, `unknown_codes`, and every
    `reason_code` of its rows - in the order met."""
    seen = []

    def add(c):
        if isinstance(c, str) and c and c not in seen:
            seen.append(c)
    for c in (f.get("losses") or {}) if isinstance(f.get("losses"), dict) else ():
        add(c)
    for c in f.get("unknown_codes") or [] if isinstance(f.get("unknown_codes"), list) else ():
        add(c)

    def walk(x):
        if isinstance(x, dict):
            add(x.get("reason_code"))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(f)
    return seen
