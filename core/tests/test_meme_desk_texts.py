"""CF-0762: the meme desk's Russian texts are for the user - the command
center shows them as they are. No file path, no task id, no config key or
API name, an em dash « — » not « - »; the technical detail is in `en`.
Refusal codes are unchanged.

What is checked (no network, no live bank - stand-ins and temp folders):
* a guard over the module: every Russian string literal of
  scripts/meme_desk.py (f-strings with their holes as `{x}`; docstrings and
  the page's HTML aside) has no path, no CF- id and no « - »;
* the texts that interpolate a path or a key at run time - the cutout's
  availability, over_ceiling, too_many_frames, the embedding's failure, an
  unknown channel - carry the detail in `en` only;
* the cutout's refusals and the trim's note have a Russian counterpart
  (cutout_refused_ru, trim_note_ru / phrase_ru) while the English line stays.
"""
import ast
import contextlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))
import meme_desk as desk  # noqa: E402

CYR = re.compile(r"[а-яё]", re.I)
PATH = re.compile(r"(?:^|[\s'\"(«])(?:~|\.{1,2})?/[\w.-]"     # /abs, ~/x, ./x
                  r"|[\w.-]+/[\w.-]+\.[a-z]{2,4}\b"          # dir/file.ext
                  r"|\w/[\w.-]+/")                           # a/b/
TASK_ID = re.compile(r"\b(?:CF|CC)-\d")


def faults(text):
    """What makes `text` not the user's: a path, a task id, a hyphen-dash."""
    out = []
    if PATH.search(text):
        out.append("path")
    if TASK_ID.search(text):
        out.append("task id")
    if " - " in text or text.startswith("- ") or text.endswith(" -"):
        out.append("hyphen-dash")
    return out


@contextlib.contextmanager
def stand_ins(**kw):
    old = {k: getattr(desk, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(desk, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(desk, k, v)


def russian_literals():
    """(line, text) of every Russian string literal the module can hand out."""
    tree = ast.parse((ROOT / "scripts" / "meme_desk.py").read_text())
    skip = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant):
            skip.add(id(n.body[0].value))
        if isinstance(n, ast.JoinedStr):
            skip.update(id(v) for v in n.values)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{x}" for v in n.values)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip:
            text = n.value
        else:
            continue
        if CYR.search(text) and "<" not in text:               # the page's HTML is not a reason
            out.append((n.lineno, text))
    return out


def test_every_russian_literal_is_the_users():
    found = russian_literals()
    assert len(found) > 100, len(found)                       # the scan sees the module
    bad = [(line, faults(t), t) for line, t in found if faults(t)]
    assert not bad, "\n".join(f"meme_desk.py:{ln} {f}: {t!r}" for ln, f, t in bad)


def test_the_guard_catches_what_it_is_for():
    assert faults("нет /home/x/.venv/bin/python") == ["path"]
    assert faults("потолок (inserts/meme.json asset_floor)") == ["path"]
    assert faults("на другой ОС её нет (CF-0654)") == ["task id"]
    assert faults("указаны и канал, и банк - нужно что-то одно") == ["hyphen-dash"]
    assert faults("указаны и канал, и банк — нужно что-то одно") == []
    assert faults("cut — да или нет (true/false); мем(а/ов)") == []


def test_cutout_availability_keeps_paths_and_ids_in_en():
    real_env = os.environ.get("MEME_VISION_PY")
    try:
        with stand_ins(_platform=lambda: ("linux", "")):
            ok, text, en = desk._cutout_check()
            assert ok is False and "linux" in text and not faults(text), text
            assert "CF-0654" in en and "rembg" in en, en
        with stand_ins(_platform=lambda: ("darwin", "13.6")):
            ok, text, en = desk._cutout_check()
            assert ok is False and "13.6" in text and "VNGenerate" not in text, text
            assert "VNGenerateForegroundInstanceMaskRequest" in en, en
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["MEME_VISION_PY"] = str(Path(tmp) / "no-python")
            with stand_ins(_platform=lambda: ("darwin", "26.0")):
                ok, text, en = desk._cutout_check()
                assert ok is False and not faults(text) and "no-python" not in text, text
                assert "no-python" in en, en
            os.environ["MEME_VISION_PY"] = sys.executable
            with stand_ins(_platform=lambda: ("darwin", "26.0"),
                           VISION_HELPER=Path(tmp) / "gone.py"):
                ok, text, en = desk._cutout_check()
                assert ok is False and not faults(text) and "gone.py" not in text, text
                assert "gone.py" in en, en
            with stand_ins(_platform=lambda: ("darwin", "26.0"),
                           VISION_HELPER=Path(sys.executable)):
                ok, text, en = desk._cutout_check()
                assert ok is True and sys.executable not in text and sys.executable in en
    finally:
        if real_env is None:
            os.environ.pop("MEME_VISION_PY", None)
        else:
            os.environ["MEME_VISION_PY"] = real_env


def test_over_ceiling_names_no_config_key():
    with stand_ins(media_size=lambda p: (100, 100), fit_box=lambda repo: (900, 900),
                   max_upscale=lambda repo: 2.0):
        try:
            desk._floor("/somewhere/small.png", ROOT)
        except desk.MemeDeskError as e:
            assert e.code == "over_ceiling", e.code
            assert "допустимо до 2.0" in e.text and "9.00 раза" in e.text, e.text
            assert "asset_floor" not in e.text and not faults(e.text), e.text
            assert "max_upscale_factor" in e.en, e.en
        else:
            raise AssertionError("a 9x stretch passed the floor")


def test_too_many_frames_says_the_limit_in_frames():
    e = desk._too_many(301, 0.5)
    assert e.code == "too_many_frames"
    assert f"не больше {desk.MAX_SHEET_FRAMES} кадров" in e.text and "потолок" not in e.text
    assert not faults(e.text), e.text


def test_the_embeddings_failure_is_in_words():
    with tempfile.TemporaryDirectory() as tmp:
        with stand_ins(indexer_python=lambda: Path(tmp) / "no-venv" / "python"):
            r = desk._embed_run(None, Path(tmp))
    assert r["done"] is False and r["error"].startswith(desk.EMBED_NOT_DONE_RU), r
    assert "эмбеддинг" not in r["error"] and not faults(r["error"]), r["error"]
    assert "no-venv" in r["en"] and "index_inserts.py" in r["en"], r["en"]
    assert desk.EMBED_STEP_RU == "признаки для поиска похожих мемов"


def test_an_unknown_channel_names_no_path():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            desk.resolve_bank("nobody", root=Path(tmp), repo=Path(tmp))
        except desk.MemeDeskError as e:
            assert e.code == "no_channel" and "nobody" in e.text and not faults(e.text), e.text
            assert "nobody.json" in e.en and tmp in e.en, e.en
        else:
            raise AssertionError("an unknown channel resolved")


def test_cutout_refusals_in_russian_keep_the_english_record():
    recs = {
        "empty mask: Vision found no subject": ({"coverage": 0.004}, "пустая маска"),
        "nothing was cut: the silhouette covers": ({"coverage": 0.99}, "вырезать нечего"),
        "fragmented: 4 separate pieces": ({"parts": 4}, "распалась на 4"),
        "ragged edge: majority-filter noise": ({"edge_noise": 0.5}, "рваный край"),
        "unsure mask: 40% of the silhouette": ({"soft": 0.4}, "нечёткая маска"),
        "Vision failed: TimeoutExpired": ({}, "распознавание фигуры не сработало"),
    }
    for refused, (m, word) in recs.items():
        ru = desk.cutout_refused_ru(dict(m, refused=refused))
        assert word in ru and not faults(ru) and not ru.startswith(refused[:5]), (refused, ru)
    assert "заново" in desk.cutout_refused_ru({"file": None})
    # an old record without its measures still reads
    assert "пустая маска" in desk.cutout_refused_ru({"refused": "empty mask: x"})


def test_the_trims_note_has_a_russian_twin():
    m = {"size": [100, 300], "crop": [150, 0], "blank": False,
         "top": {"rows": 150, "tone": "white", "share": 0.5},
         "bottom": {"rows": 3, "tone": "black", "share": 0.01}}
    en, ru = desk.trim_note(m), desk.trim_note_ru(m)
    assert en.startswith("CF-0534") and "blank caption panel cut off" in en, en
    assert ru.startswith("срезана пустая полоса под подпись: сверху 150 белых строк (50%)"), ru
    assert "снизу 3 чёрных строк (1.0%) — меньше порога" in ru and not faults(ru), ru
    assert desk.band_phrase_ru(m) == "сверху 150 белых строк (50%), снизу 3 чёрных строк (1%)"
    assert desk.band_phrase_ru({"blank": True}) == "один тон целиком"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
