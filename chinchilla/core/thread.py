"""Data shared by the panel, the agent and the session store."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


@dataclass
class Capture:
    """One screen cut, stored as a JPEG next to the session file."""

    id: str = field(default_factory=new_id)
    path: str = ""
    width: int = 0
    height: int = 0
    created_at: float = field(default_factory=now)
    rect: dict[str, int] | None = None
    label: str = ""
    # a cut belongs to the turn that sends it; later messages in the same
    # conversation are plain text unless the user takes another cut
    sent: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at,
            "rect": self.rect,
            "label": self.label,
            "sent": self.sent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Capture":
        return cls(
            id=data.get("id") or new_id(),
            path=data.get("path", ""),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            created_at=float(data.get("created_at") or now()),
            rect=data.get("rect"),
            label=data.get("label", ""),
            sent=bool(data.get("sent")),
        )


@dataclass
class Source:
    title: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        return cls(title=data.get("title", ""), url=data.get("url", ""))


@dataclass
class Usage:
    """Token counters of one reply, normalised across providers.

    ``input_tokens`` always includes the cached part, so the cache ratio is a
    share of the input and not a separate bucket.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cached_ratio(self) -> float:
        return self.cached_tokens / self.input_tokens if self.input_tokens else 0.0

    @property
    def is_empty(self) -> bool:
        return not (self.input_tokens or self.output_tokens)

    def add(self, other: "Usage") -> "Usage":
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_tokens += other.cached_tokens
        return self

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Usage | None":
        if not data:
            return None
        usage = cls(
            input_tokens=int(data.get("input_tokens") or 0),
            output_tokens=int(data.get("output_tokens") or 0),
            cached_tokens=int(data.get("cached_tokens") or 0),
        )
        return None if usage.is_empty else usage

    @classmethod
    def from_payload(cls, payload: dict | None) -> "Usage":
        """Read either an OpenAI or an Anthropic usage block."""
        data = payload or {}
        if not data:
            return cls()
        if "prompt_tokens" in data:
            details = data.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens")
            if cached is None:
                cached = data.get("prompt_cache_hit_tokens")
            return cls(
                input_tokens=int(data.get("prompt_tokens") or 0),
                output_tokens=int(data.get("completion_tokens") or 0),
                cached_tokens=int(cached or 0),
            )
        # Anthropic reports cache reads and writes outside input_tokens
        reads = int(data.get("cache_read_input_tokens") or 0)
        writes = int(data.get("cache_creation_input_tokens") or 0)
        return cls(
            input_tokens=int(data.get("input_tokens") or 0) + reads + writes,
            output_tokens=int(data.get("output_tokens") or 0),
            cached_tokens=reads,
        )

    @classmethod
    def total(cls, turns: list["Turn"]) -> "Usage":
        usage = cls()
        for turn in turns:
            if turn.usage is not None:
                usage.add(turn.usage)
        return usage


@dataclass
class Turn:
    """A user or assistant message inside a session."""

    role: str = "user"
    text: str = ""
    created_at: float = field(default_factory=now)
    captures: list[str] = field(default_factory=list)
    action: str | None = None
    sources: list[Source] = field(default_factory=list)
    error: bool = False
    pending: bool = False
    usage: Usage | None = None

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "created_at": self.created_at,
            "captures": list(self.captures),
            "action": self.action,
            "sources": [source.to_dict() for source in self.sources],
            "error": self.error,
            "usage": self.usage.to_dict() if self.usage else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Turn":
        return cls(
            role=data.get("role", "user"),
            text=data.get("text", ""),
            created_at=float(data.get("created_at") or now()),
            captures=list(data.get("captures") or []),
            action=data.get("action"),
            sources=[Source.from_dict(item) for item in data.get("sources") or []],
            error=bool(data.get("error")),
            usage=Usage.from_dict(data.get("usage")),
        )
