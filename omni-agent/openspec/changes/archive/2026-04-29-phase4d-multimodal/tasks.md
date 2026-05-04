## 1. Gateway Enhancements

- [x] 1.1 Extend `StandardMessage.Attachment` for inline media
  - [x] AC: Image, voice, sticker, animation metadata carried.
- [x] 1.2 Telegram inline media handler
  - [x] AC: Highest-res photo, voice (ogg), sticker (webp), animation (first frame) handled.
- [x] 1.3 LINE inline media handler
  - [x] AC: Image, audio (m4a), sticker (png via CDN) handled.
- [x] 1.4 Proactive multimodal acknowledgment
  - [x] AC: Emoji-only ack sent within 2s (👂... / 👀...).

## 2. Brain & Model Routing

- [x] 2.1 ModelRouter modality dimension
  - [x] AC: Multimodal always routes to Gemini; Honest fallback on failure.
- [x] 2.2 Two-stage vision flow
  - [x] AC: OCR fast path (Stage 1) -> Gemini vision escalation (Stage 2).
- [x] 2.3 Sticker-via-vision unified path
  - [x] AC: Stickers interpreted as images; no metadata shortcuts.
- [x] 2.4 Content-hash placeholder for attachments
  - [x] AC: `[type:hash]` saved in conversation history.
- [x] 2.5 GIF first-frame prompt hint
  - [x] AC: "這是 GIF 首幀" hint included in Gemini prompt.

## 3. Data & Storage

- [x] 3.1 Schema migration for `voice_transcripts`
  - [x] AC: PostgreSQL table created with user_id and index.
- [x] 3.2 Voice transcript persistence
  - [x] AC: Gemini native audio transcription stored in DB.
- [x] 3.3 Storage hygiene (120hr cleanup)
  - [x] AC: Media files deleted; `voice_transcripts` preserved.

## 4. Integration & Stability

- [x] 4.1 Gemini OAuth client integration
  - [x] AC: Multimodal calls use OAuth tokens with refresh/fallback.
- [x] 4.2 BlueBubbles freeze regression
  - [x] AC: BlueBubbles remains text-only; attachments ignored.
