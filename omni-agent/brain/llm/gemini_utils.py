"""Shared helpers for Google Gemini clients."""

import base64
from google.genai import types


def build_gemini_parts(content) -> list[types.Part]:
    """Convert message content (str or multimodal list) to Gemini Part objects."""
    parts: list[types.Part] = []
    if isinstance(content, str):
        parts.append(types.Part(text=content))
    elif isinstance(content, list):
        for p in content:
            ptype = p.get("type")
            if ptype == "text":
                parts.append(types.Part(text=p["text"]))
            elif ptype in ("image", "audio", "video"):
                data = p["data"]
                if isinstance(data, str):
                    data = base64.b64decode(data)
                parts.append(types.Part(inline_data=types.Blob(
                    mime_type=p["mime_type"],
                    data=data,
                )))
    return parts
