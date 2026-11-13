"""CC-0097: the one path cutter of the API - no absolute path of this machine
leaves in an answer. Before it `api/versions.py` (CC-0030) and `api/topics.py`
(CC-0091) each kept their own copy and `api/maintenance.py` a third way of
cutting one path; they all use this module now, and so does `GET /api/version`
(CC-0003, whose `center.dist` and `agents_error` went out absolute).

* `prefixes(root)` - [(prefix, what it becomes)], the longest first: the
  factory root's and this checkout's prefixes go (a path relative to the
  root); the working copy a root worktree belongs to is its relative way up
  (`../../`);
* `scrub(obj, prefixes, outside=True)` - every string of `obj` (recursively)
  with those prefixes cut; with `outside` the home directory is `~` and any
  other absolute path `.../<its last part>` too - a URL (`https://a/b/c`)
  is left whole (CC-0098; a `file:` URL is a path and is cut); with
  `named` the root itself (a prefix that becomes "") is `.../<its last
  part>`, not `.`;
* `clean(obj, root)` - CC-0098: a body as it leaves - every refusal of the
  API (`message`, `details`, ...) goes through it in one place, the problem
  handler of `api/app.py`, and so do the answers of the batch's launch,
  stop, resume, rebuild and of the token's revocation (the factory's rows,
  argv, log paths): inside the root relative, the root itself `.../<name>`,
  the rest outside, URLs whole;
* `named(root)` - the prefixes that name the root by its last part
  (`.../<name>`) instead of cutting it - for a sentence about the root itself
  (`writes_reason`: «не git-репозиторий (.../factory)»);
* `rel(root, p)` - one path: relative to the root (as given, absolute or
  resolved - a symlinked `pipeline/` too) or to this checkout, else
  `.../<its last part>`.
"""
import os
import re
from pathlib import Path

from . import factory
from .settings import CODE

ABS = re.compile(r"(?<![\w.~])/(?:[^\s/:;,'\"()]+/)+([^\s/:;,'\"()]+)")
#: a URL other than `file:` - kept whole by the outside cut (CC-0098)
URL = re.compile(r"\b(?!file:)[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"()<>]+")
_KEPT = re.compile("\x00(\\d+)\x00")


def prefixes(root):
    """[(prefix, what it becomes)], the longest first."""
    root = Path(root)
    out = {}
    for p in (root, root.absolute(), root.resolve(), CODE, CODE.resolve()):
        out.setdefault(str(p).rstrip("/\\"), "")
    try:
        wc = Path(factory._working_copy(root)).resolve()
    except Exception:                                   # noqa: BLE001 - only a prefix less
        wc = None
    if wc is not None and str(wc) not in out:
        up = root.resolve().is_relative_to(wc)
        out[str(wc)] = os.path.relpath(wc, root.resolve()) + "/" if up else ""
    return sorted(((p, r) for p, r in out.items() if len(p) > 1),
                  key=lambda pr: len(pr[0]), reverse=True)


def named(root):
    """[(prefix, `.../<its name>/`)] of the root as given, absolute, resolved."""
    root = Path(root)
    to = f".../{root.resolve().name}/"
    out = {str(p).rstrip("/\\") for p in (root, root.absolute(), root.resolve())}
    return sorted(((p, to) for p in out if len(p) > 1), key=lambda pr: len(pr[0]), reverse=True)


def scrub(obj, prefixes, outside=True, named=False):
    """Cut the roots' prefixes out of every string; with `outside` the home
    directory is `~`, any other absolute path `.../<last part>` (a URL kept
    whole); with `named` a prefix standing alone that would become `.` is
    `.../<its last part>`."""
    if isinstance(obj, str):
        for p, r in prefixes:
            obj = obj.replace(p + "/", r)
            whole = r.rstrip("/") or (f".../{Path(p).name}" if named else ".")
            obj = re.sub(re.escape(p) + r"(?=$|[\s:;,'\"()])", lambda m: whole, obj)
        if not outside:
            return obj
        urls = []

        def keep(m):
            urls.append(m.group(0))
            return f"\x00{len(urls) - 1}\x00"
        obj = URL.sub(keep, obj)
        home = str(Path.home()).rstrip("/")
        if len(home) > 1:
            obj = obj.replace(home + "/", "~/")
        obj = ABS.sub(lambda m: ".../" + m.group(1), obj)
        return _KEPT.sub(lambda m: urls[int(m.group(1))], obj)
    if isinstance(obj, dict):
        return {k: scrub(v, prefixes, outside, named) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v, prefixes, outside, named) for v in obj]
    return obj


def clean(obj, root):
    """A refusal's or an answer's body as it leaves (CC-0098): the root's and this
    checkout's prefixes cut (a path inside relative, the root itself
    `.../<name>`), the home `~`, any other absolute path `.../<last part>`,
    a URL whole."""
    return scrub(obj, prefixes(root), outside=True, named=True)


def rel(root, p):
    """`p` relative to the root or this checkout (posix), else `.../<name>`;
    None stays None."""
    if p is None:
        return None
    p, root = Path(p), Path(root)
    for a, b in ((p, root), (p.absolute(), root.absolute()), (p.resolve(), root.resolve()),
                 (p.absolute(), CODE.absolute()), (p.resolve(), CODE.resolve())):
        try:
            return a.relative_to(b).as_posix() or "."
        except ValueError:
            continue
    return f".../{p.name}" if p.is_absolute() else p.as_posix()
