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
            elif ptype == "video" and p.get("file_uri"):
                # Gemini 可直讀的遠端影片（目前僅 YouTube URL，short-video-fetch）
                parts.append(types.Part(file_data=types.FileData(
                    file_uri=p["file_uri"],
                    mime_type=p.get("mime_type") or "video/mp4",
                )))
            elif ptype in ("image", "audio", "video"):
                data = p["data"]
                if isinstance(data, str):
                    data = base64.b64decode(data)
                parts.append(types.Part(inline_data=types.Blob(
                    mime_type=p["mime_type"],
                    data=data,
                )))
    return parts
