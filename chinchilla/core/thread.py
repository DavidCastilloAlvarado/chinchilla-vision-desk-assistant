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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at,
            "rect": self.rect,
            "label": self.label,
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

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "created_at": self.created_at,
            "captures": list(self.captures),
            "action": self.action,
            "sources": [source.to_dict() for source in self.sources],
            "error": self.error,
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
        )
