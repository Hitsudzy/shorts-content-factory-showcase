#!/usr/bin/env python3
"""CF-0567 (TH step of the root's docs/tech-footage.md) - the own-capture
candidates of a Tech topic: a public Hugging Face Space that runs the tool the
story is about, recorded by the Video Editor's recorder into the batch.

Why. ExampleTech's main footage is the factory's own screen recording of the
tool doing the thing the news says it does (the «демо» pattern); the vendors'
uploads are short proof quotes and never the base (`official_channels[].role:
proof_quote`). One host is open for recording today: `hf.space`, a Space's own
app (`channels/example-tech/footage-origin.json` `capture_hosts`). So for every
topic of a channel whose footage origins name `own_capture` this script

  1. **searches** the public Hugging Face API, no key:
     `GET https://huggingface.co/api/spaces?search=<q>&sort=likes&direction=-1&limit=20`
     for the topic's tool forms (`queries_of`: `title_ref.tool` / `model` /
     `name`, then `aliases` and `subjects`; at most MAX_QUERIES);
  2. keeps the Spaces whose id or title **names the tool** (`names_tool`: the
     form's words all among the Space's, or its spaceless form inside the
     Space's - "Qwen3-Omni" in `Qwen/Qwen3-Omni-Demo`), the **vendor's own
     org first** (`vendor_space`: the org is the topic's maker - an
     `official_channels` owner the name matches, `title_ref.vendor` / `maker`
     / `company` / `rights_holder` - or the head of the tool's own name, as
     `Qwen` is of Qwen3), then Gradio before any other SDK, then likes;
  3. reads each kept Space's **card** (`GET https://huggingface.co/api/spaces/
     <owner>/<name>`, at most MAX_CARDS_PER_TOPIC) and takes it only when it is
     running (`runtime.stage` RUNNING), public (not private, disabled or
     gated), names a licence (`cardData.license` or a `license:` tag, as the
     recorder reads it) and its app is an https page of `hf.space` that the
     channel's rule allows (`footage_licence.capture_allowed`);
  4. **records** it with the Video Editor's recorder, called by path through
     a subprocess (`agents/video-editor/scripts/capture_tool.py`, that repo's
     `.venv/bin/python` when it has one, else `python3`), into
     `<batch>/captures/` - the first directory the Footage Indexer looks in.
     The steps are a generic template (`steps_for`): wait for the app, then
     click the first Gradio example, else type a short neutral prompt into
     the first text box, then press the primary button, wait for the output,
     a short scroll; a take whose step fails is tried with the next variant,
     down to a plain look at the page (`look`). Never a sign-in field.
     The recorder's own **policy refusals** (`not_https`, `host_not_listed`,
     `host_closed`, `sign_in_host`, `robots_disallowed`, `robots_unread`,
     `space_*`, `bad_steps`, `redirect_off_host`) are final for that Space:
     logged in the topic's `capture_read` and the next Space is tried. A
     recorder that cannot run at all (`no_browser`, `assembly_failed`,
     `no_capture_rule`, a crash) stops the pass for the batch.

Limits: MAX_CAPTURES_PER_TOPIC recordings (each of a different Space) and
MAX_SPACES_PER_TOPIC Spaces tried per topic; MAX_CAPTURES_PER_BATCH
recordings, MAX_TAKES_PER_BATCH recorder runs and MAX_HF_REQUESTS_PER_BATCH
API requests per batch. Pacing is the hunter's (`fetch_rss_news.HttpClient`:
one session, the factory's User-Agent, a floor of HF_DELAY seconds between two
requests) and TAKE_GAP seconds between two recorder runs (the recorder's own
per-host floor, `PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST`, lives in one
process only).

Output: one signal per topic, `<batch>/work/capture/capture-<topic_id>.json`,
of `fetch_youtube_signal.py`'s shape (`source: "own_capture"`, `searches: 0` -
nothing is charged to YouTube), every video an own capture:

    video_id         own_capture:<id>     (the Footage Indexer's ingest key)
    kind             own_capture
    title            "<Space title> - own capture (<owner>/<name>)"
    source_url       the page recorded (https://<sub>.hf.space/)
    capture_file     the recording, absolute (<batch>/captures/own_capture-<id>.mp4)
    duration_seconds the take's length
    capture          {space, page, final_url, space_licence, sdk, likes,
                      vendor_space, steps_variant, steps, steps_done, sidecar,
                      captured_at, id, file_id, recorder}

plus `capture_read` (the queries, the requests, every Space looked at and
why it was or was not recorded, every take with the recorder's verdict).
`footage_candidates.py` takes it beside the topic's feed file
(`--signal <batch>/work/capture/capture-<topic_id>.json:<topic_id>`); the
own captures lead the candidate list and carry `capture_file`.

A channel without the `own_capture` origin (ExampleFilm, ExampleScience)
gets "nothing to record" and no files.

Usage (from the agent root):
  scripts/fetch_own_capture.py --batch <batch-dir> [--topic <id>] \\
      [--max-captures-per-topic 2] [--max-captures 6] [--recorder <capture_tool.py>]
  scripts/fetch_own_capture.py "Qwen3-Omni" --channel example-tech --out-dir <dir>
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _channel_data import channel_data  # noqa: E402
from _footage_licence import footage_licence  # noqa: E402
from _runlog import factory_root, runlog  # noqa: E402
import footage_origin  # noqa: E402

SOURCE = "own_capture"
KIND = footage_origin.OWN_CAPTURE
HEAD = footage_origin.OWN_CAPTURE_HEAD
FILE_PREFIX = "own_capture-"
SIDECAR_SUFFIX = ".own_capture.json"

HF_SEARCH = "https://huggingface.co/api/spaces"
HF_CARD = "https://huggingface.co/api/spaces/{space}"
SPACE_HOST = "hf.space"
# The factory's own name on every request (fetch_rss_news.DEFAULT_USER_AGENT's
# form), and the hunter's floor between two requests.
USER_AGENT = "shorts-content-factory/trend-hunter (personal research tool; fetch_own_capture.py)"
HF_DELAY = 1.0
TIMEOUT = 20

MAX_QUERIES = 2
SEARCH_LIMIT = 20
MAX_CARDS_PER_TOPIC = 6
MAX_SPACES_PER_TOPIC = 3
MAX_CAPTURES_PER_TOPIC = 2
MAX_CAPTURES_PER_BATCH = 6
MAX_TAKES_PER_BATCH = 12
MAX_HF_REQUESTS_PER_BATCH = 40
TAKE_GAP = 2.0
CAPTURE_SECONDS = 45.0
RECORDER_TIMEOUT = 300

# The recorder's verdicts (agents/video-editor/scripts/capture_tool.py).
POLICY_REFUSALS = ("not_https", "host_not_listed", "host_closed", "sign_in_host",
                   "robots_disallowed", "robots_unread", "space_not_named",
                   "space_card_unread", "space_not_public", "space_no_licence",
                   "bad_steps", "redirect_off_host")
RECORDER_DOWN = ("no_browser", "assembly_failed", "no_capture_rule", "recorder_error")

# Words a tool's name shares with everything - never the match on their own.
GENERIC = {"ai", "the", "a", "an", "of", "and", "model", "models", "new", "app", "demo",
           "space", "chat", "bot", "by", "for", "with", "v", "beta", "preview", "release",
           "launch", "launches", "update", "open", "source"}
# A vendor whose Hugging Face org is not its own name.
VENDOR_ORGS = {"meta": ("facebook", "metallama"), "google": ("google", "googledeepmind"),
               "deepmind": ("google", "googledeepmind"), "aws": ("amazon",),
               "amazon web services": ("amazon",), "hugging face": ("huggingface",),
               "huggingface": ("huggingface",)}

# CF-0813 - the subject check (`subject_verdict`). A Space's org with one of
# these after (or before) the maker's name is the maker's (`deepseek-ai`).
OFFICIAL_SUFFIXES = {"", "ai", "labs", "lab", "research", "hq", "inc", "official", "team",
                     "org", "llama", "arc"}
# A word that says the Space is something else that only uses the name -
# refused unless the owner is the maker.
OTHER_SUBJECT_WORDS = {"game", "games", "gaming", "lander", "toy", "toys", "fan", "fans",
                       "fanmade", "fanart", "fanfic", "parody", "meme", "memes", "quiz",
                       "trivia", "simulator", "simulation", "sim", "arcade", "puzzle",
                       "joke", "jokes", "prank", "rpg", "roleplay", "racing", "racer",
                       "clicker", "tetris", "snake", "pong", "flappy", "maze", "horoscope",
                       "tarot", "entertainment", "fake", "tribute"}
# A title that calls the Space a demo of what it names.
DEMO_WORDS = {"demo", "demos", "playground", "chat", "chatbot", "inference", "webui"}
SUBJECT_REFUSAL = "own_capture_other_subject"

# The step template. Selectors are Gradio's (4.x/5.x): the app container, the
# examples dataset (gallery or table), the text box and the primary button.
APP_SELECTOR = ".gradio-container"
PAGE_SELECTOR = "body"
EXAMPLE_SELECTOR = ("button.gallery-item, .gallery button, tr.tr-body, "
                    "[data-testid='examples'] button")
TEXT_SELECTOR = "textarea[data-testid='textbox'], textarea"
SUBMIT_SELECTOR = "button.primary, button.lg.primary, button[variant='primary']"
TEXT_PROMPT = "Explain in one sentence what you can do."
IMAGE_PROMPT = "a lighthouse on a rocky coast at sunset, photo"
IMAGE_TAGS = ("text-to-image", "image-generation", "diffusers", "stable-diffusion",
              "text-to-video", "video-generation")
VARIANTS_GRADIO = ("examples", "prompt", "look")
VARIANTS_OTHER = ("look",)


class CaptureSearchError(Exception):
    pass


class BudgetSpent(Exception):
    pass


class HfApi:
    """The Hugging Face API on the hunter's HTTP client (one session, the
    factory's User-Agent, HF_DELAY between requests). A test hands in a
    stand-in with the same `json(url, params=None)`."""

    def __init__(self, client=None):
        if client is None:
            from fetch_rss_news import HttpClient
            client = HttpClient(user_agent=USER_AGENT, timeout=TIMEOUT, delay=HF_DELAY)
        self.client = client
        self.calls = 0

    def json(self, url, params=None):
        self.calls += 1
        resp = self.client.get(url, params=params)
        if resp.status_code != 200:
            raise CaptureSearchError(f"{url}: HTTP {resp.status_code}")
        return resp.json()


class Budget:
    """The batch's caps, spent across topics."""

    def __init__(self, requests=MAX_HF_REQUESTS_PER_BATCH, takes=MAX_TAKES_PER_BATCH,
                 captures=MAX_CAPTURES_PER_BATCH):
        self.requests, self.takes, self.captures = requests, takes, captures
        self.spent = {"requests": 0, "takes": 0, "captures": 0}
        self.recorder_down = None

    def left(self, what):
        return getattr(self, what) - self.spent[what]

    def spend(self, what):
        if self.left(what) <= 0:
            raise BudgetSpent(what)
        self.spent[what] += 1


# --------------------------------------------------------------------------
# which topics, which queries, which Spaces
# --------------------------------------------------------------------------

def tokens(text):
    return [t for t in re.split(r"[^0-9a-z]+", str(text or "").lower()) if t]


def compact(text):
    return "".join(tokens(text))


def queries_of(title_ref, limit=MAX_QUERIES):
    """The tool's forms to search with: `tool`, `model`, `name`, then
    `aliases` and `subjects` - distinct, at most `limit`."""
    ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    out, seen = [], set()
    for f in [ref.get("tool"), ref.get("model"), ref.get("name")] + \
            list(ref.get("aliases") or []) + list(ref.get("subjects") or []):
        f = str(f or "").strip()
        if f and compact(f) and compact(f) not in seen:
            seen.add(compact(f))
            out.append(f)
    return out[:limit]


_VERSION_TAIL = re.compile(r"^(v?\d+[a-z0-9]*)?$")


def word_run(want, have):
    """Whether the words `want` stand in `have` as whole words (CF-0831).

    The same rule as content-researcher's `scripts/demo_base.py`
    `space_names()` (repeated here, not imported across repos): the words
    stand consecutively, or the name written together (`deepseek` of
    deep-seek) is a run of whole words written together - optionally
    followed by a version (`ChatGPT` in `ChatGPT4`, `GPT` in `gpt4o`). A
    longer word that only starts with the name is another name: "OpenCode"
    is not in `OpenCoder-LLM/OpenCoder-8B-Instruct`."""
    if not want or not have:
        return False
    flat = "".join(want)
    for i in range(len(have)):
        if have[i:i + len(want)] == want:
            return True
        run = ""
        for w in have[i:]:
            run += w
            if run == flat:
                return True
            if run.startswith(flat) and _VERSION_TAIL.match(run[len(flat):]):
                return True
            if len(run) >= len(flat):
                break
    return False


def names_tool(space_id, title, forms):
    """Whether a Space (its `owner/name` and its card title) names one of the
    tool's forms: every non-generic word of the form among the Space's words,
    or the form as whole words of the Space's name or of its title
    (`word_run`: consecutive, or written together, a version tail allowed).
    Never a prefix of a longer word - before CF-0831 the form's spaceless
    spelling was taken anywhere inside the Space's, and "OpenCode" took
    `OpenCoder-LLM/OpenCoder-8B-Instruct` as its own capture."""
    have_id, have_title = tokens(space_id), tokens(title)
    words = set(have_id) | set(have_title)
    for form in forms:
        want = [t for t in tokens(form) if t not in GENERIC]
        if not want:
            continue
        if set(want) <= words:
            return True
        if word_run(want, have_id) or word_run(want, have_title):
            return True
    return False


def vendor_names(title_ref, config):
    """The topic's makers, spaceless and lower case: `vendor` / `maker` /
    `company` / `rights_holder` / `network` of the title_ref, and the owners
    of every `official_channels` entry whose name pattern the tool's name
    matches ("OpenAI's GPT-6" -> openai)."""
    ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    out = set()
    for k in ("vendor", "maker", "company", "rights_holder", "network"):
        v = ref.get(k)
        for one in (v if isinstance(v, list) else [v]):
            if compact(one):
                out.add(compact(one))
    text = " ".join(str(ref.get(k) or "") for k in ("name", "tool", "model", "title"))
    for entry in (config or {}).get("official_channels") or []:
        rx = entry.get("_re")
        if rx is not None and rx.search(text):
            out.update(compact(o) for o in entry.get("owners") or [] if compact(o))
    return out


def _org_is(org, name):
    """Whether a Space's org (spaceless) is one name of the maker: the name
    itself, its Hugging Face org (VENDOR_ORGS), or the name with one official
    suffix on either side (`deepseek-ai` of DeepSeek, `mistral` of Mistral AI)
    - never a longer word that merely starts with it (`AnthropicallyHuggingFaces`
    is not Anthropic, CF-0813)."""
    if not org or not name:
        return False
    if org == name or org in {compact(o) for o in VENDOR_ORGS.get(name, ())}:
        return True
    if len(name) >= 3 and org.startswith(name) and org[len(name):] in OFFICIAL_SUFFIXES:
        return True
    return len(org) >= 3 and name.startswith(org) and name[len(org):] in OFFICIAL_SUFFIXES


def form_heads(forms):
    """The org a tool's own name may come from: the letters that open its
    first word (`Qwen` of Qwen3-Omni), and its leading words short of the
    whole name (`Tesla` of Tesla Roadster) - 3+ characters each."""
    out = set()
    for f in forms:
        toks = tokens(f)
        if not toks:
            continue
        m = re.match(r"[a-z]+", toks[0])
        if m and len(m.group(0)) >= 3:
            out.add(m.group(0))
        for k in range(1, len(toks)):
            head = "".join(toks[:k])
            if len(head) >= 3:
                out.add(head)
    return out


def vendor_space(space_id, vendors, forms):
    """Whether the Space's org is the topic's maker (`_org_is`): a maker's
    name (or its Hugging Face org, VENDOR_ORGS), or the head of the tool's own
    name (`Qwen` of Qwen3-Omni, `Tesla` of Tesla Roadster; `form_heads`)."""
    org = compact(str(space_id).split("/")[0])
    if not org:
        return False
    return any(_org_is(org, v) for v in set(vendors) | form_heads(forms))


# --------------------------------------------------------------------------
# the subject (CF-0813): the Space shows the news's subject, not a toy on its name
# --------------------------------------------------------------------------

def subject_text(card):
    """The card's own words about the Space: `cardData.title`,
    `cardData.short_description`, the API's `ai_short_description` and
    `ai_category`."""
    card = card if isinstance(card, dict) else {}
    data = card.get("cardData") or {}
    return {"title": str(data.get("title") or card.get("title") or ""),
            "description": " ".join(str(x) for x in (data.get("short_description"),
                                                      card.get("short_description"),
                                                      card.get("ai_short_description"))
                                    if str(x or "").strip()),
            "category": str(card.get("ai_category") or "")}


def stop_signal(space_id, card, forms):
    """The first stop word (OTHER_SUBJECT_WORDS: game, lander, toy, fan,
    parody, meme, quiz, simulator ...) in the Space's name, its card's title,
    description, category or tags - a word of the tool's own name never
    counts (a topic about a game engine may say "game") - or None."""
    own = {t for f in forms for t in tokens(f)}
    txt = subject_text(card)
    words = tokens(str(space_id).split("/")[-1]) + tokens(txt["title"]) + \
        tokens(txt["description"]) + tokens(txt["category"]) + \
        [t for tag in (card or {}).get("tags") or [] for t in tokens(tag)]
    for w in words:
        if w in OTHER_SUBJECT_WORDS and w not in own:
            return w
    return None


def subject_verdict(space_id, card, forms, vendor):
    """-> (how, None) when the Space demonstrates the topic's subject, else
    (None, detail). Deterministic, in this order:

      1. `official`  - the Space's org is the maker's (`vendor_space`): taken;
      2. a stop word (`stop_signal`) in its name or card: refused - a game, a
         toy, a fan app, a meme or a parody that only uses the name;
      3. `card_names` - the card's description (`short_description` /
         `ai_short_description`) names the tool: taken (a third-party Space
         whose card says it runs the model);
      4. `title_demo` - the card's title names the tool and calls itself a
         demo (DEMO_WORDS: demo, playground, chat, inference ...): taken;
      5. anything else - the name matched, the card does not say it shows
         the subject: refused.

    `card` may be None (only the Space's name is known yet): then only 1-2
    are asked, and a Space that passes them is not decided (`(None, None)`)."""
    if vendor:
        return "official", None
    stop = stop_signal(space_id, card, forms)
    if stop:
        return None, (f"{stop!r} in the Space's name or card - a {stop} that uses the "
                      f"name, not the subject itself, and the owner is not the maker")
    if card is None:
        return None, None
    txt = subject_text(card)
    if txt["description"] and names_tool("", txt["description"], forms):
        return "card_names", None
    title = txt["title"] or str(space_id).split("/")[-1]
    if names_tool("", title, forms) and set(tokens(title)) & DEMO_WORDS:
        return "title_demo", None
    return None, ("the card does not say the Space demonstrates the subject (its "
                  "description names no form of it, its title is no demo of it) and the "
                  "owner is not the maker - the name matched, the subject did not")


def space_licence(card):
    """The licence a Space's card names (`cardData.license`, else a
    `license:<id>` tag) - the recorder's reading - or None."""
    if not isinstance(card, dict):
        return None
    lic = (card.get("cardData") or {}).get("license")
    if isinstance(lic, list):
        lic = ", ".join(str(x) for x in lic if str(x).strip())
    if isinstance(lic, str) and lic.strip():
        return lic.strip()
    for tag in card.get("tags") or []:
        if isinstance(tag, str) and tag.startswith("license:") and tag[8:].strip():
            return tag[8:].strip()
    return None


def space_page(card, space_id):
    """The Space's own app page: the card's `host`, else its `subdomain`,
    else Hugging Face's spelling of `owner/name`."""
    host = str((card or {}).get("host") or "").strip().rstrip("/")
    if host.startswith("https://") and host.endswith("." + SPACE_HOST):
        return host + "/"
    sub = (card or {}).get("subdomain") or re.sub(r"[/_.]+", "-", str(space_id).lower()).strip("-")
    return f"https://{sub}.{SPACE_HOST}/"


def card_verdict(card, space_id, doc):
    """-> (info, None) for a Space that may be recorded, else (None, reason)."""
    card = card if isinstance(card, dict) else {}
    if card.get("private"):
        return None, "private"
    if card.get("disabled"):
        return None, "disabled"
    if card.get("gated") not in (None, False, "false"):
        return None, f"gated ({card.get('gated')}) - not a public page (Q26)"
    stage = str((card.get("runtime") or {}).get("stage") or "")
    if not stage.startswith("RUNNING"):
        return None, f"not running (runtime.stage {stage or 'unknown'!r})"
    lic = space_licence(card)
    if not lic:
        return None, "the card names no licence - a Space with none is not recorded"
    page = space_page(card, space_id)
    if footage_licence is not None:
        ok, why = footage_licence.capture_allowed(page, doc)
        if not ok:
            return None, f"the channel's rule: {why}"
    sdk = card.get("sdk") or (card.get("cardData") or {}).get("sdk")
    return {"space": space_id, "page": page, "space_licence": lic, "sdk": sdk,
            "likes": card.get("likes"), "title": (card.get("cardData") or {}).get("title")
            or space_id.split("/")[-1], "tags": [str(t) for t in card.get("tags") or []],
            "stage": stage}, None


# --------------------------------------------------------------------------
# the steps
# --------------------------------------------------------------------------

def neutral_prompt(info):
    tags = " ".join((info or {}).get("tags") or []).lower()
    return IMAGE_PROMPT if any(t in tags for t in IMAGE_TAGS) else TEXT_PROMPT


def variants_for(info):
    return VARIANTS_GRADIO if str((info or {}).get("sdk") or "").lower() == "gradio" \
        else VARIANTS_OTHER


def steps_for(info, variant):
    """The generic take of one variant - `examples`: click the first example
    and run it; `prompt`: type a short neutral prompt into the first text box
    and run it; `look`: the page as it loads, and a short scroll. Every
    variant waits for the app first and ends on the output."""
    gradio = str((info or {}).get("sdk") or "").lower() == "gradio"
    head = [{"do": "wait_for", "selector": APP_SELECTOR if gradio else PAGE_SELECTOR,
             "seconds": 20},
            {"do": "wait", "seconds": 1.5}]
    tail = [{"do": "wait", "seconds": 10},
            {"do": "scroll", "by": 400, "seconds": 1.5},
            {"do": "wait", "seconds": 1.5}]
    if variant == "examples":
        return head + [{"do": "click", "selector": EXAMPLE_SELECTOR},
                       {"do": "wait", "seconds": 1},
                       {"do": "click", "selector": SUBMIT_SELECTOR}] + tail
    if variant == "prompt":
        return head + [{"do": "type", "selector": TEXT_SELECTOR, "text": neutral_prompt(info)},
                       {"do": "wait", "seconds": 0.5},
                       {"do": "click", "selector": SUBMIT_SELECTOR}] + tail
    return head + [{"do": "wait", "seconds": 3},
                   {"do": "scroll", "by": 400, "seconds": 1.5},
                   {"do": "wait", "seconds": 1.5}]


# --------------------------------------------------------------------------
# the recorder
# --------------------------------------------------------------------------

def recorder_command(script=None, root=None):
    """-> [python, capture_tool.py]: the Video Editor's recorder by path from
    the factory root, run with that repo's `.venv/bin/python` when it has one,
    else `python3`."""
    if script is None:
        root = Path(root) if root else factory_root()
        script = root / "agents" / "video-editor" / "scripts" / "capture_tool.py"
    script = Path(script)
    venv = script.parent.parent / ".venv" / "bin" / "python"
    return [str(venv) if venv.exists() else "python3", str(script)]


def run_recorder(argv, timeout=RECORDER_TIMEOUT):
    """-> (returncode, stdout, stderr). A test hands in a stand-in."""
    out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return out.returncode, out.stdout, out.stderr


def slug(text, most=48):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:most].strip("-") or "page"


def capture_id(space_id, now, used=()):
    """`<owner-name slug>-<UTC stamp>` - the recorder's own form - made
    unique within the run."""
    base = f"{slug(space_id.replace('/', '-'))}-{now.strftime('%Y%m%dt%H%M%Sz')}"
    cid, n = base, 2
    while cid in used:
        cid, n = f"{base}-{n}", n + 1
    return re.sub(r"[^A-Za-z0-9_-]", "_", cid)


def take(info, variant, channel, out_dir, steps_dir, cmd, runner, cid,
         seconds=CAPTURE_SECONDS):
    """One recorder run -> its verdict `{ok, reason, detail, file, record, steps}`."""
    steps = steps_for(info, variant)
    steps_path = Path(steps_dir) / f"steps-{cid}.json"
    steps_path.write_text(json.dumps(steps, indent=1))
    argv = list(cmd) + [info["page"], str(out_dir), "--channel", channel,
                        "--steps", str(steps_path), "--space", info["space"],
                        "--max-seconds", str(seconds), "--id", cid]
    try:
        code, out, err = runner(argv, RECORDER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "detail": f"no verdict in {RECORDER_TIMEOUT} s",
                "steps": steps}
    except OSError as exc:
        return {"ok": False, "reason": "recorder_error", "detail": str(exc), "steps": steps}
    try:
        res = json.loads(out or "")
    except ValueError:
        return {"ok": False, "reason": "recorder_error", "steps": steps,
                "detail": (err or out or f"exit {code}").strip()[-300:]}
    res = res if isinstance(res, dict) else {}
    ok = bool(res.get("ok")) and code == 0 and bool(res.get("file"))
    return {"ok": ok, "reason": None if ok else (res.get("reason") or f"exit {code}"),
            "detail": res.get("detail"), "file": res.get("file"), "sidecar": res.get("sidecar"),
            "record": res.get("record") if isinstance(res.get("record"), dict) else {},
            "steps": steps}


def capture_record(info, verdict, cid, vendor):
    rec = verdict.get("record") or {}
    vid = rec.get("id") if str(rec.get("id") or "").startswith(HEAD) else f"{HEAD}{cid}"
    mp4 = str(Path(verdict["file"]).resolve())
    return {
        "video_id": vid,
        "kind": KIND,
        "title": f"{info['title']} - own capture ({info['space']})",
        "description": "",
        "channel_title": "own capture",
        "channel_id": None,
        "published_at": rec.get("captured_at"),
        "duration_seconds": rec.get("duration_s"),
        "view_count": None,
        "facets": [SOURCE],
        "yt_license": None,
        "source_url": info["page"],
        "capture_file": mp4,
        "capture": {
            "space": info["space"], "page": info["page"], "final_url": rec.get("final_url"),
            "space_licence": info["space_licence"], "sdk": info.get("sdk"),
            "likes": info.get("likes"), "vendor_space": vendor,
            "subject_match": info.get("subject_match"),
            "steps_variant": verdict.get("variant"), "steps": verdict.get("steps"),
            "steps_done": rec.get("steps_done"), "sidecar": verdict.get("sidecar"),
            "captured_at": rec.get("captured_at"), "id": vid[len(HEAD):],
            "file_id": rec.get("file_id") or Path(mp4).stem,
            "recorder": "agents/video-editor/scripts/capture_tool.py (CF-0567)"},
    }


# --------------------------------------------------------------------------
# one topic
# --------------------------------------------------------------------------

def capture_hosts_open(doc):
    """Whether the channel's rule opens `hf.space` for recording."""
    if footage_licence is None:
        return False
    return footage_licence.capture_allowed(f"https://x.{SPACE_HOST}/", doc)[0]


def topic_capture(title_ref, api, config, doc, *, channel, out_dir, steps_dir, budget,
                  cmd, runner=run_recorder, now=None, sleep=time.sleep,
                  per_topic=MAX_CAPTURES_PER_TOPIC, used=None):
    """-> the own-capture signal of one topic."""
    ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    used = used if used is not None else set()
    now = now or (lambda: datetime.now(timezone.utc))
    read = {"queries": [], "requests": 0, "spaces_seen": 0, "named": 0, "spaces": [],
            "takes": [], "captured": 0, "refusals": [], "errors": [], "stopped": None}
    head = {"source": SOURCE, "query": ref.get("name"), "facets_used": [], "searches": 0,
            "videos": [], "capture_read": read}
    if not footage_origin.has_own_capture(config):
        head["not_searched"] = "the channel's footage origins name no own_capture"
        return head
    if not capture_hosts_open(doc):
        head["not_searched"] = (f"{SPACE_HOST} is not a `capture` host of the channel's "
                                f"capture_hosts (or the rule was not found)")
        return head
    forms = queries_of(ref)
    read["queries"] = list(forms)
    if not forms:
        head["not_searched"] = "the topic names no tool to search for"
        return head
    vendors = vendor_names(ref, config)
    subject_forms = queries_of(ref, limit=None)
    found, seen = [], set()
    for q in forms:
        try:
            budget.spend("requests")
        except BudgetSpent:
            read["stopped"] = "the batch's Hugging Face request budget is spent"
            break
        read["requests"] += 1
        try:
            rows = api.json(HF_SEARCH, {"search": q, "sort": "likes", "direction": -1,
                                        "limit": SEARCH_LIMIT})
        except Exception as exc:  # noqa: BLE001 - the API down is a note, not a stop
            read["errors"].append(f"search {q!r}: {exc}")
            continue
        for row in rows if isinstance(rows, list) else []:
            sid = str((row or {}).get("id") or "")
            if "/" not in sid or sid in seen:
                continue
            seen.add(sid)
            read["spaces_seen"] += 1
            if (row or {}).get("private"):
                continue
            if not names_tool(sid, "", forms):
                continue
            read["named"] += 1
            vendor = vendor_space(sid, vendors, subject_forms)
            _, why = subject_verdict(sid, None, subject_forms, vendor)
            if why:  # a stop word in the name itself: no card is spent on it
                read["spaces"].append({"space": sid, "vendor_space": vendor,
                                       "likes": row.get("likes") or 0,
                                       "refused": SUBJECT_REFUSAL, "detail": why})
                read["refusals"].append({"space": sid, "code": SUBJECT_REFUSAL,
                                         "detail": why})
                continue
            found.append({"space": sid, "likes": row.get("likes") or 0,
                          "sdk": row.get("sdk"), "vendor": vendor})
    found.sort(key=lambda s: (0 if s["vendor"] else 1,
                              0 if str(s.get("sdk") or "").lower() == "gradio" else 1,
                              -(s["likes"] or 0)))
    cards = tried = 0
    for cand in found:
        if read["captured"] >= per_topic or tried >= MAX_SPACES_PER_TOPIC:
            break
        if cards >= MAX_CARDS_PER_TOPIC:
            read["stopped"] = read["stopped"] or f"{MAX_CARDS_PER_TOPIC} cards read for the topic"
            break
        if budget.recorder_down:
            read["stopped"] = f"the recorder cannot run: {budget.recorder_down}"
            break
        try:
            budget.spend("requests")
        except BudgetSpent:
            read["stopped"] = "the batch's Hugging Face request budget is spent"
            break
        cards += 1
        read["requests"] += 1
        row = {"space": cand["space"], "vendor_space": cand["vendor"], "likes": cand["likes"]}
        read["spaces"].append(row)
        try:
            card = api.json(HF_CARD.format(space=cand["space"]))
        except Exception as exc:  # noqa: BLE001
            row["skipped"] = f"card unread: {exc}"
            continue
        how, why = subject_verdict(cand["space"], card, subject_forms, cand["vendor"])
        if how is None:
            row.update(refused=SUBJECT_REFUSAL, detail=why)
            read["refusals"].append({"space": cand["space"], "code": SUBJECT_REFUSAL,
                                     "detail": why})
            continue
        info, why = card_verdict(card, cand["space"], doc)
        if info is None:
            row["skipped"] = why
            continue
        info["subject_match"] = how
        row.update(subject_match=how, page=info["page"], space_licence=info["space_licence"], sdk=info["sdk"])
        tried += 1
        got = None
        for variant in variants_for(info):
            if budget.left("captures") <= 0:
                read["stopped"] = "the batch's capture budget is spent"
                break
            try:
                budget.spend("takes")
            except BudgetSpent:
                read["stopped"] = "the batch's take budget is spent"
                break
            if budget.spent["takes"] > 1:
                sleep(TAKE_GAP)
            cid = capture_id(cand["space"], now(), used)
            used.add(cid)
            verdict = take(info, variant, channel, out_dir, steps_dir, cmd, runner, cid)
            verdict["variant"] = variant
            read["takes"].append({"space": cand["space"], "variant": variant, "id": cid,
                                  "ok": verdict["ok"], "reason": verdict.get("reason"),
                                  "detail": verdict.get("detail")})
            if verdict["ok"]:
                got = (verdict, cid)
                break
            if verdict.get("reason") in POLICY_REFUSALS:
                read["refusals"].append({"space": cand["space"], "code": verdict["reason"],
                                         "detail": verdict.get("detail")})
                row["refused"] = verdict["reason"]
                break
            if verdict.get("reason") in RECORDER_DOWN:
                budget.recorder_down = f"{verdict['reason']}: {verdict.get('detail')}"
                read["stopped"] = f"the recorder cannot run: {budget.recorder_down}"
                break
        if got:
            budget.spend("captures")
            read["captured"] += 1
            rec = capture_record(info, got[0], got[1], cand["vendor"])
            row["captured"] = rec["video_id"]
            head["videos"].append(rec)
        if read["stopped"] and ("budget" in read["stopped"] or "recorder" in read["stopped"]):
            break
    return head


def batch_topics(batch, wanted=()):
    for topic in (batch or {}).get("topics") or []:
        tid = topic.get("topic_id")
        if wanted and tid not in wanted:
            continue
        yield tid, dict(topic.get("title_ref") or {})


def summary_line(tid, sig):
    r = sig.get("capture_read") or {}
    if sig.get("not_searched"):
        return f"own-capture {tid}: {sig['not_searched']}"
    return (f"own-capture {tid}: {r.get('captured', 0)} recorded of {len(r.get('spaces') or [])} "
            f"Space(s) read ({r.get('named', 0)} naming the tool of {r.get('spaces_seen', 0)} "
            f"seen, {r.get('requests', 0)} requests, {len(r.get('takes') or [])} take(s), "
            f"{len(r.get('refusals') or [])} refusal(s))"
            + (f"; stopped: {r['stopped']}" if r.get("stopped") else ""))


@runlog.script("trend-hunter", "own-capture", name="fetch_own_capture.py")
def main(argv=None, api=None, runner=None, now=None, sleep=time.sleep):
    import footage_candidates as fc
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("query", nargs="?", help="a tool's name, without --batch")
    ap.add_argument("--batch", help="batch dir or 01-trend-hunter.json: one signal per topic")
    ap.add_argument("--topic", action="append", help="with --batch: only these topic ids")
    ap.add_argument("--channel", help="the channel (with --batch: the batch's `channel`)")
    ap.add_argument("--out-dir", help="where the recordings go (default <batch>/captures)")
    ap.add_argument("--signal-dir", help="where capture-<topic_id>.json go "
                                         "(default <batch>/work/capture)")
    ap.add_argument("--max-captures-per-topic", type=int, default=MAX_CAPTURES_PER_TOPIC)
    ap.add_argument("--max-captures", type=int, default=MAX_CAPTURES_PER_BATCH)
    ap.add_argument("--max-takes", type=int, default=MAX_TAKES_PER_BATCH)
    ap.add_argument("--max-requests", type=int, default=MAX_HF_REQUESTS_PER_BATCH)
    ap.add_argument("--recorder", help="the recorder script (default: the factory's "
                                       "agents/video-editor/scripts/capture_tool.py)")
    args = ap.parse_args(argv)
    batch = path = None
    if args.batch:
        path = fc._batch_path(args.batch)
        batch = json.loads(Path(path).read_text())
    channel = args.channel or (fc._batch_channel(batch) if batch is not None else None)
    try:
        config = footage_origin.load_config(channel)
        doc = channel_data.footage_origin(config["channel"])
    except (footage_origin.ConfigError, channel_data.ChannelDataError) as exc:
        print(json.dumps({"error": f"footage origin: {exc}"}), file=sys.stderr)
        return 2
    if not footage_origin.has_own_capture(config):
        print(json.dumps({"channel": config["channel"], "searches": 0, "topics": [],
                          "not_searched": "the channel's footage origins name no own_capture - "
                                          "nothing to record, nothing written"}, indent=2))
        return 0
    if batch is None and not args.query:
        ap.error("a tool's name, or --batch")
    if batch is None and not args.out_dir:
        ap.error("--out-dir is required without --batch")
    base = Path(path).parent if path else None
    out_dir = Path(args.out_dir or base / "captures")
    sig_dir = Path(args.signal_dir or (base / "work" / "capture" if base else out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    sig_dir.mkdir(parents=True, exist_ok=True)
    api = api or HfApi()
    budget = Budget(args.max_requests, args.max_takes, args.max_captures)
    common = dict(channel=config["channel"], out_dir=out_dir, steps_dir=sig_dir, budget=budget,
                  cmd=recorder_command(args.recorder), runner=runner or run_recorder, now=now,
                  sleep=sleep, per_topic=args.max_captures_per_topic, used=set())
    if batch is None:
        sig = topic_capture({"name": args.query}, api, config, doc, **common)
        print(summary_line(args.query, sig), file=sys.stderr)
        print(json.dumps(sig, ensure_ascii=False, indent=2))
        return 0
    summary = []
    for tid, ref in batch_topics(batch, set(args.topic or [])):
        sig = topic_capture(ref, api, config, doc, **common)
        target = sig_dir / f"capture-{tid}.json"
        target.write_text(json.dumps(sig, ensure_ascii=False, indent=2))
        print(summary_line(tid, sig), file=sys.stderr)
        summary.append({"topic_id": tid, "file": str(target), "captures": len(sig["videos"]),
                        "not_searched": sig.get("not_searched"),
                        "refusals": (sig.get("capture_read") or {}).get("refusals") or []})
    print(json.dumps({"searches": 0, "hf_requests": budget.spent["requests"],
                      "takes": budget.spent["takes"], "captures": budget.spent["captures"],
                      "recorder_down": budget.recorder_down, "captures_dir": str(out_dir),
                      "topics": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
