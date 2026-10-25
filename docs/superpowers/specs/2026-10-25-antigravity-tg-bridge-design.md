# Design Document: Clean Standalone Antigravity Telegram Multi-Agent Bridge

**Date:** 2026-10-25  
**Status:** Draft for User Review  
**Target Repository Path:** `/Users/daniildusinskij/All/Dev/antigravity-tg-bridge`  
**Runtime Stack:** Python 3.9+ (100% Standard Library, zero `pip` packages) + Antigravity `agentapi` CLI  

---

## 1. Purpose & Isolation Scope

Create a clean, standalone, GitHub-ready repository at `/Users/daniildusinskij/All/Dev/antigravity-tg-bridge` that packages the core Telegram <-> Antigravity multi-agent bridge for another developer (Ihor), while keeping `/Users/daniildusinskij/All/Dev/Bulka_Edu/AI/` completely untouched.

### Strict Stripping & Privacy Rules
1. **Zero personal or business data:** No tokens, API keys, chat IDs, user IDs, conversation UUIDs, names, project names, venues, or personal history from the source workspace.
2. **Zero custom skills or hardware tools:** Completely exclude `skills/`, `tools/` (TV, HomeKit, display, Xiaomi, macOS audio), `knowledge/`, `avatars/`, `board.db`, `db.py` (SQLite finance), Monobank/Health/Sanctuary/GSheets scripts, ElevenLabs TTS (`--as-voice`), Telegram Business Secretary, `/girls`, `/training-sell`, `/balance`, and `/council`.
3. **Zero spontaneous discussion themes:** Completely remove the background timer loop (`scheduler_loop`) and all hardcoded personal/life discussion scenarios.

---

## 2. Repository Structure

```text
/Users/daniildusinskij/All/Dev/antigravity-tg-bridge/
├── agents/
│   ├── orchestrator.md              # Universal COO / dispatcher role template
│   ├── tech_lead.md                 # Software architecture & code execution role template
│   ├── product.md                   # Product strategy & UX/roadmap role template
│   ├── analyst.md                   # Data, metrics & research role template
│   └── mentor.md                    # Focus, decision-making & reflection role template
├── bridge/
│   └── tg_reply.py                  # CLI utility called by Antigravity to reply / run agent chains
├── config/
│   └── settings.example.json        # Sanitized configuration template (copied to settings.json on first run)
├── memory/
│   └── master_profile.example.md    # Clean shared context template (copied to master_profile.md on first run)
├── bot.py                           # Main Telegram long-polling daemon & Antigravity dispatcher
├── start.sh                         # Startup script (config bootstrap, optional macOS caffeinate, bot launch)
├── .gitignore                       # Ignores config/settings.json, config/runtime_env.json, data/, memory/master_profile.md
└── README.md                        # Step-by-step Ukrainian setup & customization guide
```

Runtime-generated directories (`data/voice/`, `data/uploads/`, `config/settings.json`, `config/runtime_env.json`, `memory/master_profile.md`) are created automatically on startup and excluded from Git via `.gitignore`.

---

## 3. Configuration Schema (`config/settings.example.json`)

All roles, topics, and trigger keywords are driven by `config/settings.json` so the user can rename, add, or remove agents without editing Python code:

- `owner_name`: Display name used by agents when addressing the user (default: `"Ігор"`).
- `whitelist_user_ids`: Array of allowed Telegram numeric user IDs (e.g. `[123456789]`). When empty on first launch, `bot.py` logs incoming `user_id` to terminal output and blocks execution until configured.
- `bot_token`: Primary Telegram bot token (used for `#General`, `/setup`, `/settings`, and as fallback for roles without a dedicated bot token).
- `agent_tokens`: Optional map `{ "<role_key>": "<telegram_bot_token>" }` allowing each agent to speak from its own Telegram bot account.
- `orchestrator_conversation_id`: Target Antigravity conversation UUID receiving dispatched prompts.
- `agentapi_bin`: Optional explicit path to `agentapi` binary (auto-detected from `~/.gemini/antigravity/bin/agentapi` or `PATH` when empty).
- `group_chat_id`: Populated automatically when `/setup` is executed in a Telegram Supergroup with Topics enabled.
- `topics`: Populated automatically by `/setup` (`{ "<topic_key>": <message_thread_id> }`).
- `roles`: Map of role definitions:
  - `orchestrator` (`🎯 Оркестратор`, topic `general` / `#General`)
  - `tech_lead` (`💻 Tech Lead`, topic `dev` -> `💻 Розробка`)
  - `product` (`📦 Продукт`, topic `product` -> `📦 Продукт`)
  - `analyst` (`📊 Аналітика`, topic `analytics` -> `📊 Аналітика`)
  - `mentor` (`🧠 Ментор`, topic `mentor` -> `🧠 Ментор`)
  Each role entry contains `title`, `short_label`, `topic_key`, `topic_name`, `welcome_text`, `keywords` (regex list for addressing specific agents in `#General`), and `prompt_file`.
- `available_models`, `models`, `fallback_ladder`, `selected_settings_agent`: Interactive model switcher state for `/settings` and automatic quota fallback.

---

## 4. Component Behavior & Data Flow

### 4.1 Inbound Flow (`bot.py`)
1. **Authorization Guard:** Accepts messages strictly from `whitelist_user_ids` in both private DM and supergroups (plus Telegram's `@GroupAnonymousBot` `1087968824` inside the bound `group_chat_id`). Unauthorized messages are ignored and logged locally to `data/blocked_requests.jsonl`.
2. **Built-in Commands:**
   - `/start` - health check reply confirming the bridge is online.
   - `/setup` - creates missing Forum Topics defined in `settings["roles"]` plus `⚙️ Параметри`, posts each role's `welcome_text`, and pins the interactive model selector in `⚙️ Параметри`.
   - `/settings` - renders inline keyboard to inspect and switch active LLM labels per role.
   - `/set_token <role> <token>` - binds a dedicated Telegram bot token to a role on the fly and spawns its DM/callback listener thread.
3. **Media Handling:** Downloads inbound `photo`, `document`, `voice`, and `audio` attachments into `data/uploads/` or `data/voice/`. Converts `.ogg` voice notes to `16kHz` mono `.wav` if `ffmpeg` is available (falls back to original `.ogg` if `ffmpeg` is not installed).
4. **Role Routing:**
   - Determines default role from the message's `message_thread_id`.
   - Scans text for collective triggers (`рада`, `команда`, `обговоріть`, `дискусія`, `всі разом`) or role-specific `keywords` from `settings["roles"]` to support multi-agent discussions.
   - Sends native `typing` indicator (`sendChatAction`) from the matched agent bot(s).
5. **Antigravity Dispatch & Auto-Heal:**
   - Builds a structured prompt referencing `memory/master_profile.md`, `agents/<role>.md`, media path (if any), and the exact `python3 <repo>/bridge/tg_reply.py ...` command to reply.
   - Invokes `agentapi send-message --title="TG: <topic>" <conversation_id> <prompt>`.
   - If `agentapi` fails due to a stale port or restarted Antigravity `language_server`, `auto_heal_runtime_env()` inspects running `language_server` processes (`ps aux` + `lsof`), validates candidate ports via `agentapi get-conversation-metadata <conversation_id>`, updates `config/runtime_env.json`, and retries delivery once.
   - If `agentapi` reports quota exhaustion (`429` / `resource_exhausted`), `trigger_quota_fallback()` advances the role to the next entry in `fallback_ladder` and notifies the group.
6. **Hot Reload:** `watch_code_reload()` monitors `bot.py` modification time and restarts the process via `os.execv` when updated.

### 4.2 Outbound Flow (`bridge/tg_reply.py`)
1. **Single Message Mode:** Sends replies via `--topic`, `--role`, `--chat-id`, `--thread-id`, `--reply-to`, `--edit-id`, and `--text` / `--text-file`.
2. **Single-Bot vs Multi-Bot Transparency:**
   - If `agent_tokens[role]` is configured, sends directly from that specialist bot.
   - If only the main `bot_token` is configured (or if a specialist bot gets HTTP `403` in DM), automatically prefixes the message with the role badge (e.g. `💻 **[Tech Lead]**`) and sends via `bot_token`.
3. **Safe Formatting & Chunking:** Splits messages exceeding `3900` characters and retries without `parse_mode="Markdown"` if Telegram rejects unescaped Markdown symbols.
4. **Multi-Agent Delayed Chains (`--chain-json` & `--delay`):**
   - Sends the first `delay: 0` message synchronously and spawns a detached background worker (`subprocess.Popen(..., start_new_session=True)`) for subsequent replies.
   - Simulates natural human-like pauses (`delay` seconds), triggers `typing` indicator up to 4 seconds before each reply, and threads replies via `"reply_to": "prev"` or `"first"`.

---

## 5. Verification Criteria

1. **Syntax & CLI Check:** `python3 -m py_compile bot.py bridge/tg_reply.py` and `python3 bridge/tg_reply.py --help` succeed with exit code `0`.
2. **Bootstrap Check:** Running `bash -n start.sh` succeeds; `settings.example.json` is valid JSON with dynamic role definitions.
3. **Zero-Leakage Audit:** Automated `grep -rniE` scan across `/Users/daniildusinskij/All/Dev/antigravity-tg-bridge` confirms zero occurrences of source tokens, `738460434`, `a876e1ad`, `daniildusinskij`, `winsou`, `bulka`, `tab_edu`, `nesvit`, `elevenlabs`, or personal names from the source workspace.
4. **Git Initialization:** Clean `git init` inside `/Users/daniildusinskij/All/Dev/antigravity-tg-bridge` with `.gitignore` verified via `git status`.
