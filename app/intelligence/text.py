"""Single source of truth for the text fed to the embedder."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def incident_text(title: str, description: str) -> str:
    title = _WS.sub(" ", (title or "").strip())
    description = _WS.sub(" ", (description or "").strip())
    text = f"{title}. {description}" if title and description else title or description
    return text.lower()
