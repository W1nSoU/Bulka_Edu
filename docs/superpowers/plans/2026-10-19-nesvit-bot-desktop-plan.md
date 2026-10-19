# Implementation Plan: Standalone Nesvit_Bot on Desktop

**Spec Reference:** `docs/superpowers/specs/2026-10-19-nesvit-bot-desktop-design.md`  
**Execution Date:** 2026-10-19  
**Target Path:** `/Users/daniildusinskij/Desktop/Nesvit_Bot`

---

## Task Breakdown

- [ ] **Task 1: Scaffold Directory Structure**
  - Create `/Users/daniildusinskij/Desktop/Nesvit_Bot` and subdirectories: `config/`, `knowledge/`, `prompts/`, `core/`, `data/voice/`, `data/logs/`.

- [ ] **Task 2: Configure Settings & Runtime Environment**
  - Create `config/settings.json` with Bot Token `8951032148:AAH9IsJxSbzumeAZCOYV2c8f3CGl-TOUc7M`, ElevenLabs Key, Voice ID `iEmO1KNYMPBds0Zul8Pm`, speed `1.28`.
  - Create `config/runtime_env.json` copying current Antigravity connection environment.

- [ ] **Task 3: Extract & Clean Nesvit Knowledge Base**
  - Compile `knowledge/nesvit_codex_clean.md` from `AI/knowledge/nesvit/nesvit_codex.md` and `workbook_extracted.txt`.
  - Verify complete absence of Danik's personal details via automated grep.
  - Compile `knowledge/workbook_clean.md` covering the 7 signs of reciprocity and Fact vs Explanation.

- [ ] **Task 4: Create System Prompt**
  - Create `prompts/nesvit_system_prompt.md` embedding Nesvit's clinical mentor mindset, calm tone, and response protocols.

- [ ] **Task 5: Implement Core Modules**
  - Create `core/tts_engine.py` (ElevenLabs + ffmpeg 1.28x OGG Opus).
  - Create `core/agent_bridge.py` (`agentapi` dispatch with auto-healing).
  - Create `core/tg_reply.py` (Telegram API communication).

- [ ] **Task 6: Implement Main Daemon & Entry Points**
  - Create `bot.py` (Telegram polling, message dispatcher, audio downloader, command handlers).
  - Create `requirements.txt`, `start.sh` (executable), and `README.md`.

- [ ] **Task 7: Comprehensive Testing & Verification**
  - Test clean knowledge grep.
  - Test TTS generation standalone.
  - Test Telegram bot API connectivity.
