# Design Document: Standalone Nesvit_Bot on Desktop

**Date:** 2026-10-19  
**Status:** Approved by User  
**Target Path:** `/Users/daniildusinskij/Desktop/Nesvit_Bot`  
**Bot Token:** `8951032148:AAH9IsJxSbzumeAZCOYV2c8f3CGl-TOUc7M`  
**TTS Provider:** ElevenLabs (Voice ID: `iEmO1KNYMPBds0Zul8Pm`, Speed: `1.28x`)

---

## 1. Executive Summary & Purpose

The user requires a completely standalone Telegram bot named **`Nesvit_Bot`**, residing outside the main `Bulka_Edu` repository at `/Users/daniildusinskij/Desktop/Nesvit_Bot`.
The bot replicates the psychological methodology, voice, and mentoring style of **Kostiantyn Nesvit** (project "Between Sessions" / «Між сесіями»).

### Key Isolation Requirement
- **Zero personal data leakage:** The new bot's knowledge base and prompts must contain NO personal data about Danik, his businesses (Bulka Edu, TAB Agency), financial numbers, girlfriends, acquaintances (Nazar, Ksyukha, Yulia, Sofia, Marichka, Fame, etc.), or specific local venues.
- The root Coalition files in `/Users/daniildusinskij/All/Dev/Bulka_Edu/AI/` must remain completely untouched.

---

## 2. Architecture & File Structure

```text
/Users/daniildusinskij/Desktop/Nesvit_Bot/
├── config/
│   ├── settings.json            # Bot token, ElevenLabs API key, Voice ID, conversation_id, whitelist
│   └── runtime_env.json         # Cached agentapi runtime connection params (port, csrf_token)
├── knowledge/
│   ├── nesvit_codex_clean.md    # Pure Nesvit methodology: axioms, principles, protocols, exercises
│   └── workbook_clean.md        # Official course workbook: 7 signs of reciprocity, Fact vs Explanation
├── prompts/
│   └── nesvit_system_prompt.md  # System instructions defining persona, speech tone, response rules
├── core/
│   ├── tts_engine.py            # ElevenLabs TTS generation + ffmpeg (atempo=1.28) -> Telegram Voice (.ogg Opus)
│   ├── agent_bridge.py          # Dispatches user requests to Antigravity via agentapi, with auto-healing
│   └── tg_reply.py              # Telegram API wrapper: sendMessage, sendVoice, sendChatAction (typing/voice)
├── data/
│   ├── voice/                   # Inbound and outbound temporary audio files
│   └── logs/                    # Bot runtime logs
├── bot.py                       # Main polling daemon: handles incoming messages, commands, and voices
├── start.sh                     # 1-click launch script
├── requirements.txt             # Minimal dependencies
└── README.md                    # Setup and usage guide
```

---

## 3. Knowledge Base Content (Clean Nesvit Methodology)

The knowledge base in `knowledge/nesvit_codex_clean.md` contains the distillation of over 230,000 words of Nesvit's materials:
1. **Core Psychological Axioms:**
   - «Все, що ми не змінюємо - ми схвалюємо» (radical personal responsibility).
   - «Ми маємо рівно стільки, скільки готові витримати при втраті» (psychological capacity to hold value).
   - «Кулемет ППШ замість снайперки» (imperfect high-velocity action over paralyzing perfectionism).
   - «Зовнішні опори крихкі - опора тільки всередині».
   - «Внутрішній дозвіл» (self-permission to rest, decline, or step back).
   - «Зрада неефективній сімейній системі» (separation from parental patterns without guilt).
2. **Relationship Framework:**
   - 7 objective criteria of reciprocity:
     1. Initiative (natural movement without dragging).
     2. Consistency (stable baseline over 2-3 weeks).
     3. Time & Place (conscious planning vs residual late-night crumbs).
     4. Interest in personality (beyond flirtation/physical attraction).
     5. Planning (joint horizons for upcoming days/weekends).
     6. Post-intimacy behavior (warmth vs sudden distancing).
     7. Clarity of intent (capacity for direct dialogue).
   - Method «Факт проти пояснення» (camcorder test: objective reality vs hopeful rationalizations).
   - Reciprocity Map: «Вже бачу» / «Хочу з'ясувати» / «Хочу обговорити».
3. **Session Protocol:**
   - Step 1: Validation & grounding (warm tea, calming tone, normalising cognitive fatigue).
   - Step 2: Dissecting facts from interpretations.
   - Step 3: Returning agency (where is the client's choice and secondary gain?).
   - Step 4: Concrete micro-action rated "4 out of 5" (action without heroism).

---

## 4. Voice Engine & Audio Pipeline

- **TTS Engine:** ElevenLabs API via direct HTTPS requests.
  - API Key: stored in `config/settings.json`.
  - Voice ID: `iEmO1KNYMPBds0Zul8Pm` (Kostiantyn Nesvit voice clone).
  - Post-processing: `ffmpeg -i input.mp3 -filter:a "atempo=1.28" -c:a libopus -b:a 64k output.ogg`.
  - Sent as native Telegram Voice Note (`sendVoice`).
- **Probability & Triggers:**
  - Direct command or flag: `/voice` triggers voice response.
  - Inbound voice note: 50% probability of answering with voice.
  - Inbound text: 20% probability of voice note, or configurable in `settings.json`.

---

## 5. Antigravity AgentAPI Integration

- `agent_bridge.py` utilizes the Antigravity `agentapi` binary (`/Users/daniildusinskij/.gemini/antigravity/bin/agentapi`).
- Dynamic port & CSRF auto-healing detects running `language_server` instances when connections reset.
- Configurable `conversation_id`: Allows Danik to link the bot to a dedicated conversation in Antigravity.
- Bot command `/set_chat <CONVERSATION_ID>` allows switching the target conversation directly from Telegram.

---

## 6. Verification & Test Plan

1. **Cleanliness Verification:** Grep `Desktop/Nesvit_Bot/` for forbidden tokens (`Данік`, `Bulka`, `TAB`, `Ксюха`, `Назар`, `Fame`, etc.) to guarantee 100% absence.
2. **Config Verification:** Confirm `settings.json` has the correct bot token, ElevenLabs key, and voice parameters.
3. **TTS Verification:** Run standalone test script to synthesize sample speech at 1.28x speed and verify `.ogg` format.
4. **Daemon Launch Verification:** Verify `bot.py` initializes without errors and connects to Telegram Bot API.
