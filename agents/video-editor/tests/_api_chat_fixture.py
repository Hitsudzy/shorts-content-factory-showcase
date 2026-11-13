"""CF-0690: stand-ins for an `api_chat` graphic - a protocol of a call that
never happened (the shape of the root's gemini_api.ask), the channel's
`api_demo` block as ExampleTech's footage-origin.json carries it (a copy, no
live file is read) and the chat order a script would place. No network."""
import copy

CONFIG = {
    "provider": "gemini_api",
    "models": [{"id": "gemini-2.5-flash", "display_name": "Gemini 2.5 Flash",
                "matches": ["gemini 2.5 flash"]},
               {"id": "gemini-2.5-flash-lite", "display_name": "Gemini 2.5 Flash-Lite",
                "matches": ["gemini 2.5 flash lite"]}],
    "default_model": "gemini-2.5-flash",
    "prompts": ["Write a four-line poem about a robot learning to paint."],
    "max_calls_per_batch": 3, "min_interval_seconds": 5, "timeout_seconds": 60,
    "max_answer_chars": 280,
}
PROMPT = "Write a four-line poem about a robot learning to paint."
ANSWER = ("Its steel hand trembles, holding the brush,\n"
          "A smear of blue where circuits used to rush.\n"
          "It learns that crooked lines can still be true,\n"
          "And paints the sky a slightly wrong-but-lovely hue.")
RECORD_ID = "api-demo-gemini-25-flash"
LABEL = "Gemini 2.5 Flash · via API"

PROTOCOL = {
    "provider": "gemini_api",
    "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-2.5-flash:generateContent",
    "model_requested": "gemini-2.5-flash", "model_version": "gemini-2.5-flash",
    "prompt": PROMPT, "generation_config": {"temperature": 0.7},
    "answer": ANSWER, "finish_reason": "STOP", "prompt_feedback": None, "citation": False,
    "usage": {"promptTokenCount": 12, "candidatesTokenCount": 48},
    "response_id": "resp-stand-in", "requested_at": "2026-10-12T09:00:00Z",
    "answered_at": "2026-10-12T09:00:03Z", "key_source": "environment", "status": "ok",
    "skip_reason": None,
}

CHAT = {
    "graphic_id": "chat1", "template": "api_chat", "record_id": RECORD_ID,
    "data": {"model_label": LABEL, "prompt": PROMPT, "answer": ANSWER},
    "values": [],
}

# the worst case the template is sized for: a 48-character label, a
# 160-character prompt and a 280-character answer, line breaks in both
WORST = {
    "model_label": "Gemini 2.5 Flash-Lite Preview Build · via API",
    "prompt": ("Summarize the plot of a heist story you invent, in three sentences.\n"
               "Keep it light, give the crew a funny name, and end on a twist that nobody at all "
               "expects."),
    "answer": ("The Velvet Owls plan to lift a jade clock from a museum gala by posing as the "
               "string quartet.\nMidway through the second waltz the clock starts chiming on "
               "its own, and every guest turns to stare at the stage.\nThe twist: the curator "
               "hired them to steal it back from a forger she…"),
}


def chat(**data):
    g = copy.deepcopy(CHAT)
    g["data"].update(data)
    return g


def protocol(**fields):
    p = copy.deepcopy(PROTOCOL)
    p.update(fields)
    return p
