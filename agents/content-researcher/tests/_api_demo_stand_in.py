"""CF-0690: stand-ins for "a demo via API" - a protocol of a Gemini API call
as `shared/gemini/gemini_api.ask` leaves it, the topic's `api_demo_record`,
the Trend Hunter's `api_demo_record` support_text piece (the shape of
`agents/trend-hunter/scripts/api_demo_text.py`) and an `api_chat` graphic
ordered from them. No network, no key: every value is written here."""
import copy

TOPIC = "tech-001"
RECORD_ID = "api-demo-tech-001"
PROMPT = "Explain how a rainbow forms in two sentences."
ANSWER = ("A rainbow forms when sunlight enters raindrops, bends, reflects off the back of "
          "each drop and bends again on the way out. Because each colour bends by a slightly "
          "different amount, the white light spreads into a band of colours across the sky.")
MODEL_VERSION = "gemini-2.5-flash"
DISPLAY = "Gemini 2.5 Flash"
ANSWERED_AT = "2026-10-12T09:30:00Z"
CONFIG = {"provider": "gemini_api",
          "models": [{"id": "gemini-2.5-flash", "display_name": "Gemini 2.5 Flash",
                      "matches": ["gemini 2.5 flash"]},
                     {"id": "gemini-2.5-flash-lite", "display_name": "Gemini 2.5 Flash-Lite",
                      "matches": ["gemini 2.5 flash lite"]}],
          "default_model": "gemini-2.5-flash", "prompts": [PROMPT],
          "max_calls_per_batch": 3, "min_interval_seconds": 5, "timeout_seconds": 60,
          "max_answer_chars": 280}


def protocol(**over):
    p = {"provider": "gemini_api",
         "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/"
                     "gemini-2.5-flash:generateContent",
         "model_requested": "gemini-2.5-flash", "model_version": MODEL_VERSION,
         "prompt": PROMPT, "generation_config": {"temperature": 0.7}, "answer": ANSWER,
         "finish_reason": "STOP", "prompt_feedback": None, "citation": False,
         "usage": {"promptTokenCount": 9, "candidatesTokenCount": 60},
         "response_id": "resp-1", "requested_at": "2026-10-12T09:29:58Z",
         "answered_at": ANSWERED_AT, "key_source": "environment", "status": "ok",
         "skip_reason": None}
    p.update(over)
    return p


def record(**over):
    return {"record_id": RECORD_ID, "protocol": protocol(**over)}


def piece():
    """The Trend Hunter's piece of the record (api_demo_text.piece)."""
    text = (f"On 2026-10-12 the factory sent this prompt to {DISPLAY} through the Gemini API: "
            f"«{PROMPT}». {DISPLAY} answered: «{ANSWER}».")
    return {"id": RECORD_ID, "kind": "api_demo_record", "source": "api_demo",
            "title": f"API demo of {DISPLAY}", "url": protocol()["endpoint"],
            "revision_id": None, "revised_at": None, "fetched_at": ANSWERED_AT,
            "model_requested": "gemini-2.5-flash", "model_version": MODEL_VERSION,
            "display_name": DISPLAY, "prompt": PROMPT, "record_id": RECORD_ID,
            "not_a_fact": True, "text": text}


def shown(answer=ANSWER, max_chars=280):
    """api_demo.shown_answer, re-done here only for the stand-in's own answer
    (it fits 280, so it is the answer itself)."""
    assert len(answer) <= max_chars
    return answer


def chat(gid="g9", **data_over):
    data = {"model_label": f"{DISPLAY} · via API", "prompt": PROMPT, "answer": shown(),
            "date": "2026-10-12"}
    data.update(data_over)
    return {"graphic_id": gid, "template": "api_chat", "record_id": RECORD_ID, "data": data}


def topic(with_record=True, extra_pieces=()):
    t = {"topic_id": TOPIC, "support_text": [copy.deepcopy(p) for p in extra_pieces],
         "support_check": {"state": "ok"}}
    if with_record:
        t["api_demo_record"] = record()
        t["support_text"].append(piece())
    return t
