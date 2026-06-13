# Local CPU STT Implementation Tasks

- [x] **Infrastructure Updates**
  - [x] Update `compose.yml` to add `whisper-models` volume.
  - [x] Update `brain/Dockerfile` to install `ffmpeg`.
  - [x] Update `brain/requirements.txt` to add `faster-whisper`.
- [x] **Brain Service Logic**
  - [x] Update `brain/main.py` to initialize `WhisperModel` in lifespan.
  - [x] Add `_transcribe_voice_local` helper function.
  - [x] Update `/chat` endpoint to intercept voice messages and use local STT.
  - [x] Implement echo suffix in `BrainResponse`.
- [x] **Verification**
  - [x] Verify Dockerfile builds correctly (syntax check).
  - [x] Verify `main.py` syntax and imports.
