## Why

Cindy currently understands only text. Family members regularly send images, voice messages, stickers, and GIFs through Telegram and LINE — all of which Cindy ignores or fails to interpret. 

This phase adds multimodal input handling for Telegram and LINE, using Gemini 2.5 Flash/Pro as the unified multimodal backend. This is a critical prerequisite for Phase 5 (Family Preference Awareness), as preference learning requires capturing the full richness of family interactions.

## What Changes

### New Capabilities
- **multimodal-perception**: Ability to process images, voice, stickers, and animations from Telegram and LINE.
- **voice-persistence**: Automated transcription and storage of voice messages for future retrieval.
- **honest-fallback**: Non-evasive error handling when multimodal processing fails.

### Modified Capabilities
- **model-routing**: Enhanced ModelRouter to force Gemini selection for multimodal inputs.
- **gateway-senses**: Expanded Telegram and LINE handlers to download and forward media attachments.
- **vision-pipeline**: Two-stage vision flow (OCR fast path → Gemini vision escalation).

## Impact

- **User Experience**: Cindy now reacts to photos, stickers, and voice, feeling more like a "family butler" who is present in the conversation.
- **Data Layer**: New `voice_transcripts` table added to PostgreSQL.
- **Storage**: Media files are now tracked in `file_workspace_log` and subject to 120-hour cleanup.
- **Security**: BlueBubbles remains text-only (frozen) to ensure stability during this phase.

## Open Questions (Resolved)

- ✅ **Sticker cache**: Deferred to Phase 4D.1 to keep scope tight.
- ✅ **GIF handling**: First-frame extraction implemented with prompt hints.
- ✅ **Acknowledge style**: Emoji-only acknowledgments (👂... / 👀...) used for social presence.
