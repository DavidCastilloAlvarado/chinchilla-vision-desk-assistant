"""Session files: one JSON document per conversation plus its captures."""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .. import paths
from ..core import capture as capture_module
from ..core.thread import Capture, Source, Turn
from . import config

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
DEFAULT_TITLE = "New session"


def new_session_id() -> str:
    """Lexicographically sortable id: 10 chars of time + 10 of randomness."""
    milliseconds = int(time.time() * 1000)
    stamp = "".join(_ALPHABET[(milliseconds >> shift) & 31] for shift in range(45, -1, -5))
    return stamp + "".join(secrets.choice(_ALPHABET) for _ in range(10))


def session_path(session_id: str) -> Path:
    return paths.sessions_dir() / f"{session_id}.json"


def capture_path(capture_id: str) -> Path:
    return paths.captures_dir() / f"{capture_id}.jpg"


@dataclass
class Session:
    id: str = field(default_factory=new_session_id)
    title: str = DEFAULT_TITLE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    provider: str = ""
    model: str = ""
    turns: list[Turn] = field(default_factory=list)
    captures: list[Capture] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    web_enabled: bool = False

    # ----------------------------------------------------------------- basics

    @property
    def path(self) -> Path:
        return session_path(self.id)

    @property
    def is_empty(self) -> bool:
        return not self.turns and not self.captures

    def capture(self, capture_id: str) -> Capture | None:
        return next((item for item in self.captures if item.id == capture_id), None)

    def last_capture(self) -> Capture | None:
        return self.captures[-1] if self.captures else None

    def turn_count(self) -> int:
        return len([turn for turn in self.turns if turn.role == "user"])

    def preview(self, limit: int = 70) -> str:
        """Last thing the user asked, which reads better than the answer."""
        for wanted in ("user", "assistant"):
            for turn in reversed(self.turns):
                if turn.role == wanted and turn.text:
                    return " ".join(turn.text.split())[:limit]
        return ""

    # ---------------------------------------------------------------- mutate

    def add_turn(self, turn: Turn) -> Turn:
        self.turns.append(turn)
        self.touch()
        return turn

    def add_capture(self, image: Image.Image) -> Capture:
        paths.ensure_dirs()
        capture = Capture(width=image.width, height=image.height)
        saved = capture_module.save_jpeg(image, capture_path(capture.id))
        capture.path = str(saved)
        self.captures.append(capture)
        self.touch()
        return capture

    def add_sources(self, sources: list[Source]) -> None:
        for source in sources:
            if source.url and all(existing.url != source.url for existing in self.sources):
                self.sources.append(source)

    def autotitle(self, text: str) -> None:
        if self.title and self.title != DEFAULT_TITLE:
            return
        words = re.sub(r"\s+", " ", (text or "").strip()).split(" ")
        title = " ".join(word for word in words if word)[:48]
        if title:
            self.title = title[0].upper() + title[1:]

    def rename(self, title: str) -> None:
        cleaned = " ".join((title or "").split())
        self.title = cleaned[:80] or DEFAULT_TITLE
        self.touch()

    def touch(self) -> None:
        self.updated_at = time.time()

    # ------------------------------------------------------------- (de)serial

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "provider": self.provider,
            "model": self.model,
            "web_enabled": self.web_enabled,
            "turns": [turn.to_dict() for turn in self.turns],
            "captures": [capture.to_dict() for capture in self.captures],
            "sources": [source.to_dict() for source in self.sources],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            id=data.get("id") or new_session_id(),
            title=data.get("title") or DEFAULT_TITLE,
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            web_enabled=bool(data.get("web_enabled")),
            turns=[Turn.from_dict(item) for item in data.get("turns") or []],
            captures=[Capture.from_dict(item) for item in data.get("captures") or []],
            sources=[Source.from_dict(item) for item in data.get("sources") or []],
        )

    # ------------------------------------------------------------------- disk

    def save(self, directory: Path | None = None) -> Path:
        target = (directory / f"{self.id}.json") if directory else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    @classmethod
    def load(cls, session_id: str) -> "Session | None":
        path = session_path(session_id)
        if not path.is_file():
            return None
        return cls._read(path)

    @classmethod
    def _read(cls, path: Path) -> "Session | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        session = cls.from_dict(data)
        session.id = data.get("id") or path.stem
        return session

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
        for capture in self.captures:
            if capture.path:
                Path(capture.path).unlink(missing_ok=True)


def create_session(settings: config.Settings, title: str = DEFAULT_TITLE) -> Session:
    provider = settings.active()
    return Session(
        title=title,
        provider=provider.id,
        model=provider.model,
        web_enabled=settings.web_enabled,
    )


def list_sessions(directory: Path | None = None, limit: int = 60) -> list[Session]:
    folder = directory or paths.sessions_dir()
    if not folder.is_dir():
        return []
    sessions: list[Session] = []
    for path in folder.glob("*.json"):
        session = Session._read(path)
        if session is not None:
            sessions.append(session)
    sessions.sort(key=lambda session: session.updated_at, reverse=True)
    return sessions[:limit]


def prune(days: int, directory: Path | None = None) -> int:
    """Delete sessions untouched for more than ``days`` days. 0 means keep."""
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for session in list_sessions(directory, limit=10_000):
        if session.updated_at < cutoff:
            session.delete()
            removed += 1
    return removed
