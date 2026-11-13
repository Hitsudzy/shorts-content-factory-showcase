#!/usr/bin/env python3
"""CF-0737: one reading of where a sentence ends (`shared/factrule/sentences.py`).

The bug: «In February 2007, it was announced that Example Studios had
hired ...» was split at «Bros.», and the cut piece passed the fact check. The
rules came from the Trend Hunter's `scripts/_sentences.py`; this file pins
them in the root, where every reader of a sentence now asks them. Offline,
stand-in texts only.
"""
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "shared" / "factrule" / "sentences.py"
HUNTER = ROOT / "agents" / "trend-hunter" / "scripts" / "_sentences.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


se = _load("sentences_cf0737_test", PATH)

ARTICLE = ("In February 2007, it was announced that Example Studios had hired "
           "Dr. Smith to write it. Delver is a 2026 satirical black comedy film "
           "directed by Alejandro G. Iñárritu. It grossed $27.5 million, about "
           "2.5 million more than planned! The U.S. release came in Oct. 2007.\n"
           "Robert Downey Jr. as Tony Stark. World War I. A second line.")


def test_a_stop_after_an_abbreviation_or_an_initial_does_not_end_the_sentence():
    assert se.split_sentences(ARTICLE) == [
        "In February 2007, it was announced that Example Studios had hired "
        "Dr. Smith to write it.",
        "Delver is a 2026 satirical black comedy film directed by Alejandro G. Iñárritu.",
        "It grossed $27.5 million, about 2.5 million more than planned!",
        "The U.S. release came in Oct. 2007.",
        "Robert Downey Jr. as Tony Stark.",
        "World War I.",
        "A second line."]


def test_abbreviation_end_knows_titles_name_ends_dotted_forms_and_initials():
    for chunk in ("Example Studios", "hired Dr.", "Discovery, Inc.", "the U.S.", "e.g.",
                  "Alejandro G.", "(J.", "in Oct."):
        assert se.abbreviation_end(chunk), chunk
    for chunk in ("World War I.", "a film.", "$27.5.", "", None, "said no!"):
        assert not se.abbreviation_end(chunk), chunk


def test_cut_short_refuses_the_two_shapes_and_keeps_a_whole_sentence():
    assert se.cut_short("In February 2007, it was announced that Example Studios")
    assert se.cut_short("Delver is a 2026 satirical black comedy film directed by Alejandro G.")
    assert se.cut_short("The role went to Dr.")
    assert se.cut_short("“It was announced that Example Studios”"), "closing quotes do not hide it"
    for whole in ("The film was distributed by Example Studios",
                  "In 2022 the companies merged to become Example Studios Group.",
                  "The marketing aimed at Generation Z.",
                  "It was announced that the film grossed $27.5 million.",
                  "It was announced that Example Studios had hired him.",
                  "", None):
        assert se.cut_short(whole) is None, whole


def test_an_initial_is_one_capital_with_its_stop_not_an_all_caps_word():
    # CF-0737 regression guard (frozen 2026-09-15T1034Z, DTF St. Louis): a state
    # code, "TV", "UK" or a dotted "U.S." at the end is a whole sentence; only a
    # single capital with its full stop («Samuel L.», «Henri B.») is a cut name.
    for whole in ("Dance scenes shot at a real studio in Dunwoody, GA",
                  "Dance scenes shot at a real studio in Dunwoody, GA.",
                  "The series was filmed in Los Angeles, LA",
                  "It premiered in New York, NY.",
                  "The show was the most watched on TV",
                  "It opened first in the UK.",
                  "It opened first in the U.S.",
                  "It was the best-selling game in the U.S.",
                  "The film was shot in Washington, D.C.",
                  "It was announced that the film opens in the U.S."):
        assert se.cut_short(whole) is None, whole
    for cut in ("The lead went to Samuel L.", "The score is by Henri B.",
                "Delver is a 2026 film directed by Alejandro G."):
        assert se.cut_short(cut), cut


def test_split_at_takes_the_callers_boundary_and_keeps_every_piece():
    gap = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
    assert se.split_at("Example Studios hired him. 15 films followed.", gap) == [
        "Example Studios hired him.", "15 films followed."]
    assert se.split_at("", gap) == [""]
    closers = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”)]))\s+")
    assert se.split_at("He said “Example Studios” Then it ended.", closers) == [
        "He said “Example Studios” Then it ended."], "a closing quote after the stop is seen through"
    assert se.split_at("He said “no.” Then it ended.", closers) == [
        "He said “no.”", "Then it ended."]


def test_the_rules_are_the_hunters_where_its_copy_is_checked_out():
    """The rules moved here from the hunter; while its own `_sentences.py`
    stands, the two answer alike."""
    if not HUNTER.is_file():
        print("   no agents/trend-hunter/scripts/_sentences.py here - not compared")
        return
    hunter = _load("hunter_sentences_cf0737_test", HUNTER)
    texts = [ARTICLE, "It was announced that Example Studios", "Directed by Alejandro G.",
             "Generation Z.", "Plan B. Then more.", "He met Mr. Smith. Done."]
    for text in texts:
        assert se.split_sentences(text) == hunter.split_sentences(text), text
        assert se.cut_short(text) == hunter.cut_short(text), text
    for name in ("TITLES", "NAME_ENDS", "LETTER_NOUNS"):
        assert getattr(se, name) == getattr(hunter, name), name


def test_it_loads_by_path_with_nothing_of_this_checkout_on_sys_path():
    probe = ("import importlib.util, sys\n"
             "spec = importlib.util.spec_from_file_location('probe', sys.argv[1])\n"
             "m = importlib.util.module_from_spec(spec)\n"
             "spec.loader.exec_module(m)\n"
             "print(len(m.split_sentences('Example Studios. Next.')))\n")
    with tempfile.TemporaryDirectory(prefix="cf0737-") as cwd:
        proc = subprocess.run([sys.executable, "-I", "-c", probe, str(PATH)],
                              capture_output=True, text=True, cwd=cwd, timeout=60)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert proc.stdout.strip() == "2"


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {type(error).__name__}: {error}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
