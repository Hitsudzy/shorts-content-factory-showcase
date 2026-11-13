#!/usr/bin/env python3
"""CC-0008: a new channel from the factory's template - the one place a new
channel's files come from (the user, 08.10: «новые каналы ведём из
командного центра»).

    python3 shared/new_channel.py template [--json]
    python3 shared/new_channel.py check  <id> --name "<display name>" [--language en] [--root DIR]
    python3 shared/new_channel.py create <id> --name "<display name>" [--language en] [--root DIR]

**The template** is `shared/channel_template/` - files with `{{placeholder}}`
strings, laid out the way a channel is (docs/channel-data.md):

    config.json           -> channels/<id>.json               the minimal working config
    stance.json           -> channels/<id>/stance.json        the position, an empty skeleton
    brand/description.md  -> channels/<id>/brand/description.md   the brand folder

The config is a channel **without a pipeline** (CF-0562, `shared/channel_ids.py`):
`status: no_pipeline`, no `run_plan`, no `publisher`, and **off the schedule**
in the factory's own terms - `batch_schedule.enabled: false`, what
`no_pipeline_errors` demands of a stub and what `shared/batch_schedule.py`
`window_config` reads. Its `theme` is the template's neutral palette with
every value in `picked` (every channel config carries a theme, CF-0572).
Everything else the user adds afterwards by editing the channel.

**The inputs** (`INPUTS`) are three: the id, the display name, the language.
The id is refused when its form is wrong (`ID_RE`), when it is taken - a
channel's id or one of its `former_channel_ids` (CF-0197: a former id *is*
that channel), a directory `channels/<id>/` or `pipeline/<id>/` already on
disk (the batches there would become the new channel's), a name under
`pipeline/` that is not a channel (`runlog.NOT_A_BATCH`) - or reserved by the
caller (the API's own route names). The display name is refused when empty,
multi-line, too long, or another channel's.

**The check** is the factory's own: the rendered config goes through
`inserts/validate_inserts.py` `channel_config_errors` (the table
`validate_vocabulary` walks over every channel), and the position must be an
object of this channel. Nothing here writes git: `create` writes the files and
says what to commit; the command center (`api/channels.py` `create`) writes
and commits them as one commit.

Stdlib only; every neighbour is loaded by path. Exit 0 ok, 1 refused, 2 bad call.
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TASK = "CC-0008"
CODE = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = CODE / "shared" / "channel_template"
CHANNELS_SUBDIR = "channels"
PIPELINE_SUBDIR = "pipeline"

#: (template file, where it goes - `{id}` the channel's id)
FILES = (
    ("config.json", "channels/{id}.json"),
    ("stance.json", "channels/{id}/stance.json"),
    ("brand/description.md", "channels/{id}/brand/description.md"),
)
CONFIG_FILE = "config.json"
STANCE_FILE = "stance.json"

#: Lower-case latin letters, digits, single hyphens inside; a letter first.
#: It becomes a file name, a directory under `pipeline/` and a word in every
#: batch file, so nothing that needs quoting anywhere.
ID_RE = re.compile(r"^[a-z](?:[a-z0-9]|-(?=[a-z0-9])){1,39}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
NAME_MAX = 60
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

INPUTS = (
    {"name": "channel_id", "label": "Идентификатор", "required": True, "default": None,
     "pattern": ID_RE.pattern,
     "note": "Имя файла channels/<id>.json и папки батчей pipeline/<id>/: латиница в нижнем "
             "регистре, цифры, дефис внутри, от 2 до 40 знаков, первая - буква. Не может быть "
             "именем другого канала, в том числе прежним (former_channel_ids). Потом не "
             "меняется: переименование - отдельная работа (CF-0197)."},
    {"name": "display_name", "label": "Название", "required": True, "default": None,
     "pattern": None,
     "note": f"Как канал называется на YouTube и в центре (display_name), до {NAME_MAX} знаков, "
             f"одна строка; не название другого канала."},
    {"name": "language", "label": "Язык роликов", "required": False, "default": "en",
     "pattern": LANGUAGE_RE.pattern,
     "note": "Код языка (language конфига): en, ru, de, pt-BR... Все каналы фабрики сейчас - en."},
)


class NewChannelError(Exception):
    pass


def _load(name, rel):
    """A neighbour of this checkout, loaded by path (CF-0231), once."""
    key = f"{name}_for_new_channel"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, CODE / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    return mod


def _ids():
    return _load("channel_ids", "shared/channel_ids.py")


def _not_a_batch():
    return tuple(_load("runlog", "shared/runlog/runlog.py").NOT_A_BATCH)


def _validate_inserts():
    return _load("validate_inserts", "inserts/validate_inserts.py")


# ---------------------------------------------------------------- the template
def template_files():
    """[(template file, target pattern, text)] - the template as it is on disk."""
    out = []
    for src, dst in FILES:
        p = TEMPLATE_DIR / src
        if not p.is_file():
            raise NewChannelError(f"the template has no {src} ({p})")
        out.append((src, dst, p.read_text(encoding="utf-8")))
    return out


def template():
    """What a form for a new channel needs: the inputs with their defaults and
    notes, the files it makes, and what the new channel is in the schedule."""
    cfg = json.loads((TEMPLATE_DIR / CONFIG_FILE).read_text(encoding="utf-8"))
    ids = _ids()
    return {
        "inputs": [dict(i) for i in INPUTS],
        "files": [{"template": f"shared/channel_template/{src}", "path": dst}
                  for src, dst in FILES],
        "status": cfg.get(ids.STATUS_KEY),
        "no_pipeline": ids.NO_PIPELINE_LINE,
        "batch_schedule": cfg.get("batch_schedule"),
        "config": cfg,
    }


def normalize(values):
    """{channel_id, display_name, language}: stripped, the default filled in."""
    values = values or {}
    out = {}
    for i in INPUTS:
        v = values.get(i["name"])
        v = v.strip() if isinstance(v, str) else v
        out[i["name"]] = v if v not in (None, "") else i["default"]
    return out


def _substitute(text, values):
    def one(m):
        key = m.group(1)
        if key not in values:
            raise NewChannelError(f"the template names {{{{{key}}}}}, which is not an input")
        return str(values[key])
    return PLACEHOLDER.sub(one, text)


def _walk(node, values):
    if isinstance(node, str):
        return _substitute(node, values)
    if isinstance(node, list):
        return [_walk(x, values) for x in node]
    if isinstance(node, dict):
        return {_substitute(k, values): _walk(v, values) for k, v in node.items()}
    return node


def render(values, created=None):
    """{relative path: bytes} of the new channel. A JSON file is filled in on the
    parsed object (a name with quotes stays valid JSON) and written indent=2."""
    v = normalize(values)
    v["created"] = created or datetime.now(timezone.utc).date().isoformat()
    out = {}
    for src, dst, text in template_files():
        path = dst.format(id=v["channel_id"])
        if src.endswith(".json"):
            doc = _walk(json.loads(text), v)
            out[path] = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        else:
            out[path] = _substitute(text, v).encode("utf-8")
    return out


# ---------------------------------------------------------------- the checks
def _row(field, text):
    return {"field": field, "text": text}


def _channel_names(root):
    """{id: display_name} of the channels on disk; a file that does not read
    keeps its id (its error is its own checker's)."""
    out = {}
    for p in sorted((Path(root) / CHANNELS_SUBDIR).glob("*.json")):
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = None
        name = cfg.get("display_name") if isinstance(cfg, dict) else None
        out[p.stem] = name if isinstance(name, str) else None
    return out


def input_errors(root, values, reserved=()):
    """[{field, text}] - why the inputs cannot make a new channel; [] - they can."""
    v = normalize(values)
    root = Path(root)
    errs = []
    cid, name, lang = v["channel_id"], v["display_name"], v["language"]
    have = _channel_names(root)
    if not isinstance(cid, str) or not cid:
        errs.append(_row("channel_id", "channel_id: не задан"))
    elif not ID_RE.match(cid):
        errs.append(_row("channel_id", f"channel_id: {cid!r} - не годится: латиница в нижнем "
                                       f"регистре, цифры, дефис внутри, 2-40 знаков, первая - "
                                       f"буква"))
    else:
        owner = _ids().resolve_channel(cid, root)
        if cid in have:
            errs.append(_row("channel_id", f"channel_id: канал {cid!r} уже есть "
                                           f"(channels/{cid}.json)"))
        elif owner != cid:
            errs.append(_row("channel_id", f"channel_id: {cid!r} - прежнее имя канала {owner!r} "
                                           f"(former_channel_ids): это тот же канал"))
        elif cid in reserved or cid in _not_a_batch():
            errs.append(_row("channel_id", f"channel_id: {cid!r} - служебное имя, не канал"))
        else:
            for d in (root / CHANNELS_SUBDIR / cid, root / PIPELINE_SUBDIR / cid):
                if d.exists():
                    errs.append(_row("channel_id",
                                     f"channel_id: {d.relative_to(root).as_posix()}/ уже есть на "
                                     f"диске - его содержимое стало бы содержимым нового канала"))
    if not isinstance(name, str) or not name:
        errs.append(_row("display_name", "display_name: не задано"))
    elif "\n" in name or "\r" in name or len(name) > NAME_MAX:
        errs.append(_row("display_name", f"display_name: одна строка до {NAME_MAX} знаков"))
    else:
        twin = [c for c, n in have.items() if isinstance(n, str) and n.casefold() == name.casefold()]
        if twin:
            errs.append(_row("display_name", f"display_name: {name!r} - уже название канала "
                                             f"{twin[0]!r}"))
    if not isinstance(lang, str) or not LANGUAGE_RE.match(lang):
        errs.append(_row("language", f"language: {lang!r} - не код языка (en, ru, pt-BR...)"))
    return errs


def stance_errors(cid, stance):
    """The position has to be an object of this channel (no validator of the
    factory reads stance.json; tests/test_channel_stance.py is its guard)."""
    if not isinstance(stance, dict):
        return ["stance.json: is not a JSON object"]
    if stance.get("channel_id") != cid:
        return [f"stance.json.channel_id: must be {cid!r} (the channel it is the position of), "
                f"got {stance.get('channel_id')!r}"]
    return []


def stance_findings(cid, stance):
    """CF-0672: `stance_errors` as the center shows them - {check, code, text,
    text_ru} under validate_inserts.STANCE_CHECK."""
    vi = _validate_inserts()
    return vi.check_findings(vi.STANCE_CHECK, stance_errors(cid, stance))


def stance_text_findings(cid, raw):
    """CF-0672: (position | None, findings) of a position given as text (the
    wizard's): text that is not JSON is one finding under STANCE_PARSE_CHECK,
    the parsed position goes through `stance_findings`."""
    vi = _validate_inserts()
    try:
        stance = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        return None, vi.check_findings(vi.STANCE_PARSE_CHECK,
                                       [f"stance.json: does not parse: {e}"])
    return stance, stance_findings(cid, stance)


def stance_path_errors(cid, cfg):
    """The template's config has to name the position file the template
    writes - `channels/<id>/stance.json` - or the position has nowhere to go."""
    want = FILES[1][1].format(id=cid)
    rel = cfg.get("stance") if isinstance(cfg, dict) else None
    got = f"{CHANNELS_SUBDIR}/{rel}" if isinstance(rel, str) and rel.strip() else None
    if got is None or Path(got).as_posix() != want:
        return [f"stance.json: the template's config names no position file "
                f"({got!r}) - nowhere to write the position"]
    return []


def config_findings(root, cid, files):
    """CF-0672: every finding of the rendered files, {check, code, text,
    text_ru}: the config by `validate_inserts.channel_config_findings` (as it
    would be at `channels/<id>.json`), the template's own two (a stub; the
    position file named), the position by `stance_findings`."""
    vi = _validate_inserts()
    cfg_rel = FILES[0][1].format(id=cid)
    stance_rel = FILES[1][1].format(id=cid)
    cfg = json.loads(files[cfg_rel])
    out = vi.channel_config_findings(cfg, Path(root) / cfg_rel)
    if _ids().no_pipeline_reason(cfg, cid) is None:
        out += vi.check_findings(vi.TEMPLATE_STUB_CHECK, [
            f"{cid}.json: the template made a channel with a pipeline - a new channel "
            f"starts without one (status: no_pipeline)"])
    out += vi.check_findings(vi.TEMPLATE_STANCE_PATH_CHECK, stance_path_errors(cid, cfg))
    return out + stance_findings(cid, json.loads(files[stance_rel]))


def config_errors(root, cid, files):
    """The English lines of `config_findings` - the factory's checks of the
    rendered files."""
    return [f["text"] for f in config_findings(root, cid, files)]


def check(root, values, reserved=(), created=None):
    """{ok, channel_id, files: {rel: bytes}, input_errors: [{field, text}],
    errors: [str], findings: [{check, code, text, text_ru}]} - nothing
    written; `errors` are the English lines of `findings` (CF-0672). The config is checked only when the inputs
    pass (a bad id has no config to check)."""
    v = normalize(values)
    bad = input_errors(root, v, reserved)
    files, found = {}, []
    if not bad:
        files = render(v, created)
        found = config_findings(root, v["channel_id"], files)
    errs = [f["text"] for f in found]
    return {"ok": not bad and not errs, "channel_id": v["channel_id"], "values": v,
            "files": files, "input_errors": bad, "errors": errs, "findings": found}


def write(root, files):
    """Write the rendered files under `root` - none of them may exist. Returns
    the relative paths. No git: committing them is the caller's."""
    root = Path(root)
    there = [rel for rel in files if (root / rel).exists()]
    if there:
        raise NewChannelError(f"already on disk: {', '.join(there)}")
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return list(files)


# ---------------------------------------------------------------- the CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="new_channel.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template", help="the inputs and files of a new channel")
    t.add_argument("--json", action="store_true")
    for name, what in (("check", "check a new channel, nothing written"),
                       ("create", "check, then write the files (not committed)")):
        p = sub.add_parser(name, help=what)
        p.add_argument("channel_id")
        p.add_argument("--name", required=True, help="display name")
        p.add_argument("--language", default=None)
        p.add_argument("--root", default=str(CODE))
    a = ap.parse_args(argv)
    if a.cmd == "template":
        doc = template()
        if a.json:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        else:
            for i in doc["inputs"]:
                print(f"{i['name']}{'' if i['required'] else ' (default ' + i['default'] + ')'}: "
                      f"{i['note']}")
            for f in doc["files"]:
                print(f"{f['template']} -> {f['path']}")
        return 0
    res = check(a.root, {"channel_id": a.channel_id, "display_name": a.name,
                         "language": a.language})
    for row in res["input_errors"]:
        print(f"REFUSED {row['text']}", file=sys.stderr)
    for e in res["errors"]:
        print(f"REFUSED {e}", file=sys.stderr)
    if not res["ok"]:
        return 1
    if a.cmd == "check":
        for rel in res["files"]:
            print(f"ok {rel}")
        return 0
    for rel in write(a.root, res["files"]):
        print(f"wrote {rel}")
    print(f"commit them: git -C {a.root} add {' '.join(res['files'])} && git -C {a.root} commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
