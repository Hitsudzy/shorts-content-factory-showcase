#!/usr/bin/env python3
"""CF-0572: the channel's on-screen theme (`theme` of `channels/<id>.json`).

The reader (`shared/channel_data.theme`), the rule (`theme_errors`), the root
validator's walk (`inserts/validate_inserts.py`), the doc that describes the
keys, and ExampleFilm's theme frozen at the values the Video Editor draws
today (video-editor 3732fb7: render/src/Video.jsx THEME, scripts/
render_quote.py DEFAULT_THEME and the CardLayer / EndCard / ComparisonLine /
Captions / Watermark literals) - the videos before and after CF-0572 are the
same. The reader's and the rule's cases run on stand-ins in temp directories;
the real configs are read only as repository data, never anything live.
"""
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from _channels import stand_in_theme  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cd = _load("channel_data_for_theme_test", ROOT / "shared" / "channel_data.py")

# What the Video Editor draws for ExampleFilm at video-editor 3732fb7 - the
# values step 2 (the Editor reading plan.theme) must reproduce exactly.
REEL_FROZEN = {
    "bg": "#0B0B12", "accent": "#FFE23D", "accent2": "#7C5CFF",
    "text": "#FFFFFF", "muted": "#B9B9C6",
    "card_ground": ["#241A4D", "#12102A", "#0B0B12"],
    "end_card_ground": ["#262646", "#191930", "#12121F"],
    "badge": {"paper": "#EDE5D0", "ink": "#2E2418", "ink_muted": "#8A7A5C",
              "rule": "#C9BFA4", "accent": "#C4442E", "accent_ink": "#F4EEDD"},
    "font": {"display": '"Arial Black", "Helvetica Neue", sans-serif',
             "text": '"Helvetica Neue", Helvetica, Arial, sans-serif',
             "card": "Helvetica, Arial, sans-serif",
             "badge": '"Courier Prime", "IBM Plex Mono", monospace'},
    # render/src/components/ProceduralBg.jsx palettesFor, indices 1-5 (index 0
    # is the theme's own bg/accent/accent2/accent), same values, same order
    "procedural_palettes": [
        {"bg": "#1A0B2E", "a": "#FF6B35", "b": "#F72585", "c": "#FFD23F"},
        {"bg": "#071A2B", "a": "#00F5D4", "b": "#7B2FF7", "c": "#4CC9F0"},
        {"bg": "#1A0E0A", "a": "#FF3D5A", "b": "#FFB800", "c": "#FF0080"},
        {"bg": "#0A0E27", "a": "#00FFA3", "b": "#B026FF", "c": "#00D4FF"},
        {"bg": "#12071F", "a": "#7C5CFF", "b": "#FFE23D", "c": "#FF4D97"},
    ],
}


def make_root(tmp):
    root = Path(tmp)
    (root / "patterns").mkdir()
    (root / "patterns" / "validate_patterns.py").write_text("", encoding="utf-8")
    ch = root / "channels"
    ch.mkdir()
    (ch / "alpha.json").write_text(json.dumps({
        "channel_id": "alpha", "former_channel_ids": ["old-alpha"],
        "theme": stand_in_theme()}), encoding="utf-8")
    (ch / "beta.json").write_text(json.dumps({"channel_id": "beta"}), encoding="utf-8")
    broken = stand_in_theme()
    broken["text"] = "#202020"
    (ch / "gamma.json").write_text(json.dumps({"channel_id": "gamma", "theme": broken}),
                                   encoding="utf-8")
    return root


def refused(fn, *args, contains=None):
    try:
        fn(*args)
    except cd.ChannelDataError as exc:
        if contains:
            assert contains in str(exc), str(exc)
        return str(exc)
    raise AssertionError(f"{fn.__name__}{args} was not refused")


def errs_of(mutate):
    theme = stand_in_theme()
    mutate(theme)
    return cd.theme_errors(theme)


# ------------------------------------------------------------------ reader
def test_the_theme_is_read_for_the_named_channel_and_a_former_id():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        assert cd.theme("alpha", root) == stand_in_theme()
        assert cd.theme("old-alpha", root) == stand_in_theme()


def test_no_channel_no_theme_or_a_broken_one_is_a_refusal_not_a_borrowed_palette():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        for nothing in (None, "", "  "):
            refused(cd.theme, nothing, root, contains="no channel named")
        msg = refused(cd.theme, "beta", root, contains="channels/beta.json has no `theme`")
        assert "no factory theme to fall back to" in msg
        refused(cd.theme, "gamma", root, contains="below 4.5")
        refused(cd.theme, "delta", root, contains="unknown channel")


# ------------------------------------------------------------------ the rule
def test_a_stand_in_theme_is_valid():
    assert cd.theme_errors(stand_in_theme()) == []


def test_every_key_is_required_and_no_unknown_key_passes():
    for key in cd.THEME_COLORS + tuple(cd.THEME_GROUNDS) + ("badge", "font"):
        errs = errs_of(lambda t, k=key: t.pop(k))
        assert any(key in e for e in errs), (key, errs)
    assert any("ink_muted" in e for e in errs_of(lambda t: t["badge"].pop("ink_muted")))
    assert any("font.card" in e for e in errs_of(lambda t: t["font"].pop("card")))
    assert any("unknown" in e for e in errs_of(lambda t: t.update(acent="#FFFFFF")))
    assert any("unknown" in e for e in errs_of(lambda t: t["badge"].update(papr="#FFFFFF")))
    assert any("unknown" in e for e in errs_of(lambda t: t["font"].update(title="Arial, serif")))
    assert cd.theme_errors(None) and cd.theme_errors([])
    # picked/note are optional
    assert errs_of(lambda t: (t.pop("picked"), t.pop("note"))) == []


def test_a_colour_is_hash_rrggbb_only():
    for bad in ("#FFF", "FFFFFF", "#FFFFFFCC", "white", "rgb(1,2,3)", 16777215, None):
        errs = errs_of(lambda t, b=bad: t.update(accent2=b))
        assert any("accent2" in e and "#RRGGBB" in e for e in errs), (bad, errs)
    assert any("card_ground" in e for e in errs_of(lambda t: t["card_ground"].pop()))
    assert any("end_card_ground[1]" in e
               for e in errs_of(lambda t: t["end_card_ground"].__setitem__(1, "#12")))


def test_contrast_floors_text_45_muted_3_and_the_badge_pairs():
    assert round(cd.contrast_ratio("#FFFFFF", "#000000"), 2) == 21.0
    assert round(cd.contrast_ratio("#777777", "#777777"), 2) == 1.0
    assert any("`theme.text`" in e and "below 4.5" in e
               for e in errs_of(lambda t: t.update(text="#777777", bg="#101010")))
    # 3 <= ratio < 4.5: enough for muted, not for text
    mid = "#6A6A6A"
    assert 3.0 <= cd.contrast_ratio(mid, "#101010") < 4.5
    assert errs_of(lambda t: t.update(muted=mid)) == []
    assert any("`theme.text`" in e for e in errs_of(lambda t: t.update(text=mid)))
    assert any("`theme.muted`" in e and "below 3" in e
               for e in errs_of(lambda t: t.update(muted="#303030")))
    assert any("badge.ink`" in e and "below 4.5" in e
               for e in errs_of(lambda t: t["badge"].update(ink="#B0B0B0")))
    assert any("badge.ink_muted`" in e
               for e in errs_of(lambda t: t["badge"].update(ink_muted="#E0E0E0")))
    assert any("badge.accent_ink`" in e
               for e in errs_of(lambda t: t["badge"].update(accent_ink="#D04040")))
    assert any("`theme.accent`" in e
               for e in errs_of(lambda t: t.update(accent="#202020")))


def test_caption_colours_are_optional_hash_rrggbb_and_hold_4_5():
    """CF-0699: `caption_text`, `caption_active`, `caption_active_box` are
    optional; a caption is body text, so 4.5 - the base words on `bg`, the
    spoken word on its pill when there is one (else on `bg`)."""
    assert errs_of(lambda t: None) == []
    # Q37's three candidates on ExampleTech's ground pass
    tech_bg = "#050A14"
    for v in ({"caption_active": "#FFC53D", "caption_text": "#FFFFFF"},
              {"caption_active": "#0D1A2C", "caption_active_box": "#22D3EE",
               "caption_text": "#FFFFFF"},
              {"caption_active": "#FFFFFF", "caption_text": "#A9B8CC"}):
        assert errs_of(lambda t, v=v: t.update(bg=tech_bg, **v)) == [], v
    for key in cd.THEME_CAPTION_COLORS:
        assert key in cd.THEME_KEYS
        errs = errs_of(lambda t, k=key: t.update({k: "#FFF"}))
        assert any(f"`theme.{key}`" in e and "#RRGGBB" in e for e in errs), (key, errs)
    # the base words on the ground
    assert any("`theme.caption_text`" in e and "below 4.5" in e
               for e in errs_of(lambda t: t.update(bg="#101010", caption_text="#555555")))
    # the spoken word on the ground, no pill
    assert any("`theme.caption_active`" in e and "`theme.bg`" in e
               for e in errs_of(lambda t: t.update(bg="#101010", caption_active="#303030")))
    # with a pill, the word is read on the pill, not on the ground: dark on
    # cyan is fine although dark on the dark ground would not be
    assert errs_of(lambda t: t.update(bg="#101010", caption_active="#0D1A2C",
                                      caption_active_box="#22D3EE")) == []
    assert any("`theme.caption_active`" in e and "caption_active_box" in e
               for e in errs_of(lambda t: t.update(caption_active="#FFFFFF",
                                                   caption_active_box="#E0E0E0")))
    # a pill without caption_active: the accent is what sits on it
    assert any("`theme.accent`" in e and "caption_active_box" in e
               for e in errs_of(lambda t: t.update(accent="#F0A030",
                                                   caption_active_box="#F0B040")))


def test_a_font_is_a_css_stack_ending_in_a_generic_family():
    assert any("generic family" in e
               for e in errs_of(lambda t: t["font"].update(display='"Arial Black"')))
    assert any("empty entry" in e
               for e in errs_of(lambda t: t["font"].update(text="Arial, , serif")))
    assert any("font.badge" in e for e in errs_of(lambda t: t["font"].update(badge="")))


def test_procedural_palettes_are_optional_bg_a_b_c_hash_rrggbb():
    pal = {"bg": "#101010", "a": "#FF0000", "b": "#00FF00", "c": "#0000FF"}
    assert errs_of(lambda t: t.pop("procedural_palettes", None)) == []
    assert errs_of(lambda t: t.update(procedural_palettes=[pal, dict(pal)])) == []
    for bad in ([], {}, "x", None, [pal, "#FFFFFF"]):
        errs = errs_of(lambda t, b=bad: t.update(procedural_palettes=b))
        assert any("procedural_palettes" in e for e in errs), (bad, errs)
    errs = errs_of(lambda t: t.update(procedural_palettes=[pal, {"bg": "#101010", "a": "#FFF",
                                                                 "b": "#00FF00"}]))
    assert any("procedural_palettes[1].a" in e and "#RRGGBB" in e for e in errs), errs
    assert any("procedural_palettes[1].c" in e for e in errs), errs
    errs = errs_of(lambda t: t.update(procedural_palettes=[dict(pal, d="#FFFFFF")]))
    assert any("unknown" in e and "procedural_palettes[0]" in e for e in errs), errs


def test_picked_names_theme_keys_only():
    assert any("picked" in e for e in errs_of(lambda t: t.update(picked=["colour"])))
    assert any("picked" in e for e in errs_of(lambda t: t.update(picked="bg")))
    assert any("picked" in e for e in errs_of(lambda t: t.update(picked=["picked"])))


# ------------------------------------------------------------ the real configs


def test_example_film_keeps_the_theme_it_has_and_nothing_is_marked_picked():
    theme = cd.theme("example-film", ROOT)
    assert {k: v for k, v in theme.items() if k not in ("note", "picked")} == REEL_FROZEN
    assert "picked" not in theme


def test_the_new_channels_take_the_brand_table_and_mark_what_was_picked():
    """ROADMAP 2.3 «Brand»: the accent column, the ring, the dark end of the
    ground. What is not in the table or a brand file is listed in `picked`."""
    brand = {"example-tech": ("#22D3EE", "#2F6FED", "#050A14", "#102846"),
             "example-science": ("#34D399", "#C97A3D", "#040C09", "#0D3324")}
    for ch, (accent, ring, ground_dark, ground_light) in brand.items():
        t = cd.theme(ch, ROOT)
        assert (t["accent"], t["accent2"], t["bg"]) == (accent, ring, ground_dark), ch
        assert t["card_ground"][0] == ground_light and t["card_ground"][2] == ground_dark, ch
        assert t["badge"]["accent"] == ring, ch
        assert {"muted", "end_card_ground", "badge", "font"} <= set(t["picked"]), ch
        assert "ждёт взгляда пользователя" in t["note"], ch
        # ExampleFilm's five procedural palettes are its look, not theirs
        assert "procedural_palettes" not in t, ch


def test_example_tech_captions_are_q37_a_and_the_others_have_none():
    """CF-0699, Q37 (the user 12.10): ExampleTech's spoken word amber on white
    base words, no pill - its cyan accent on navy did not stand out. The
    graphics keep `accent`/`text`; ExampleFilm and ExampleScience are as
    they were."""
    t = cd.theme("example-tech", ROOT)
    assert (t["caption_active"], t["caption_text"]) == ("#FFC53D", "#FFFFFF")
    assert "caption_active_box" not in t
    assert (t["accent"], t["text"]) == ("#22D3EE", "#F5F1E9")
    assert "Q37" in t["note"]
    for ch in ("example-film", "example-science"):
        assert not set(cd.THEME_CAPTION_COLORS) & set(cd.theme(ch, ROOT)), ch


# ------------------------------------------------------------ validator, doc




if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
