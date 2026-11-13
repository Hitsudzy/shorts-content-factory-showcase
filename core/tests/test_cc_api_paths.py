#!/usr/bin/env python3
"""CC-0097: the API's one path cutter (`api/paths.py`) - temp trees only:

* `rel`: a path under the root is relative (as given, absolute, through a
  symlink), outside it `.../<its last part>`, a relative path stays relative,
  None stays None;
* `named`: a sentence about the root names it by its last part;
* `scrub`: the root's prefix cut everywhere, outside paths `.../<name>`, and
  with `outside=False` a URL is left whole;
* the old `_rel` copies of the modules are this one: a file outside the root
  (the token file, an env-set notify dir) comes out `.../<name>`.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from api import memes, notifications, oauth, paths, publish, rights, videos  # noqa: E402


def test_rel_inside_outside_symlink_relative_none():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        root = t / "factory"
        (root / "pipeline" / "reel").mkdir(parents=True)
        (t / "elsewhere").mkdir()
        (root / "linked").symlink_to(t / "elsewhere")
        assert paths.rel(root, root / "pipeline" / "reel") == "pipeline/reel"
        assert paths.rel(root, root.resolve() / "pipeline") == "pipeline"
        assert paths.rel(root, root) == "."
        assert paths.rel(root, t / "elsewhere" / "token.json") == ".../token.json"
        assert paths.rel(root, "publish/README.md") == "publish/README.md"
        assert paths.rel(root, None) is None
        # a symlinked dir of the root resolves outside: the as-given form wins
        assert paths.rel(root, root / "linked" / "x.json") == "linked/x.json"


def test_named_and_scrub():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "factory"
        root.mkdir()
        s = paths.scrub(f"не git-репозиторий ({root})", paths.named(root))
        assert s == "не git-репозиторий (.../factory)", s
        pre = paths.prefixes(root)
        got = paths.scrub({"a": [f"{root}/x/y", f"see {tmp}/deep/z.txt"]}, pre)
        assert got == {"a": ["x/y", "see .../z.txt"]}, got
        url = "https://youtube.com/shorts/abc"
        assert paths.scrub(f"{root}/a {url}", pre, outside=False) == f"a {url}"
        for v in (got, s):
            assert tmp not in str(v) and str(Path(tmp).resolve()) not in str(v)


def test_the_modules_rel_is_the_one_cutter():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "factory"
        root.mkdir()
        out = Path(tmp) / "secrets" / "publisher-token.json"
        for mod in (memes, notifications, oauth, publish, rights, videos):
            assert mod._rel(root, root / "publish" / "uploads.json") == "publish/uploads.json", mod
            assert mod._rel(root, out) == ".../publisher-token.json", mod


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
