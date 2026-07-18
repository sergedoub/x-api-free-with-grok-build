from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedPost:
    id: str
    text: str
    created_at: str
    author_handle: str
    author_id: str = ""
    conversation_id: str = ""
    in_reply_to: str = ""
    lang: str = ""

    @property
    def source_url(self) -> str:
        return f"https://x.com/{self.author_handle}/status/{self.id}"
