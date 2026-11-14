"""Default quick actions and the system prompt.

Actions are data: the settings dialog can rename them and rewrite their
prompts, and the defaults below are what a fresh install starts with.
"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are Chinchilla, an assistant that answers questions about screenshots "
    "of the user's screen. Be concise and concrete. When the user writes in a "
    "language different from the screen content, answer in the user's language. "
    "Use the attached screenshot as the source of truth, quote small pieces of "
    "it when it helps, and never invent text that is not visible."
)

WEB_PROMPT = (
    "You can search the web. Use the search tool when the answer depends on "
    "something outside the screenshot, and cite the URLs you used as [1], [2]. "
    "Only cite sources you actually opened."
)

DEFAULT_ACTIONS: list[dict] = [
    {
        "id": "translate",
        "title": "Translate",
        "prompt": (
            "Translate the text in the screenshot into {language}. Keep the "
            "original line breaks and structure, and do not translate code, "
            "paths or identifiers. If the text is already in {language}, say so "
            "and offer a translation into English."
        ),
        "web_default": False,
    },
    {
        "id": "explain",
        "title": "Explain",
        "prompt": (
            "Explain what is shown in the screenshot as if you were talking to "
            "a {level} engineer. Mention what it is, what is happening, and what "
            "the user should do next."
        ),
        "web_default": False,
    },
    {
        "id": "grammar",
        "title": "Fix grammar",
        "prompt": (
            "Correct the spelling, grammar and punctuation of the text in the "
            "screenshot. Reply with the corrected text first, then a short list "
            "of the changes you made."
        ),
        "web_default": False,
    },
]

ACTION_VARIABLES = ("language", "level", "text", "sources")


def render_prompt(template: str, language: str = "Spanish", level: str = "B1") -> str:
    """Fill the action placeholders that come from settings."""
    try:
        return template.format(language=language, level=level, text="", sources="")
    except (KeyError, IndexError, ValueError):
        return template
