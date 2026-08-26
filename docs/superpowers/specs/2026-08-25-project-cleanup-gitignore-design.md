# Specification: Project Cleanup & Security Hardening (.gitignore)

## Goal
Completely sanitize the project repository by removing obsolete/temporary files, untracking persistent databases from Git, cleaning OS metadata (`.DS_Store`), and establishing a robust `.gitignore` ruleset to prevent accidental leaks of sensitive tokens, private keys, database records, and AI agent artifacts to GitHub.

---

## 1. Scope & Categorization

### 1.1 Files to Ignore in `.gitignore`
- **AI Agents & Configs**: `.agents/`, `.agent/`
- **Environment & Secrets**:
  - `.env`, `.env.*`, `*.env`
  - Exception: `!.env.example` (tracked configuration template)
  - Security module secrets: `security_functions/.master_secret`, `security_functions/master_keys.db`, `security_functions/.license`, `security_functions/.salt`, `security_functions/.chksum`, `private_server/`
- **Databases & Data Storage**:
  - `*.db`, `*.sqlite`, `*.sqlite3`
  - `data/` (runtime data, FAISS indices, etc.)
- **Logs & Diagnostics**:
  - `logs/`, `*.log`, `security_functions/guard.log`
- **Python & Environment Artifacts**:
  - `__pycache__/`, `*.py[cod]`, `*$py.class`
  - `venv/`, `.venv/`, `env/`, `ENV/`
  - `build/`, `dist/`, `*.spec.bak`, `*.egg-info/`
- **Operating System & IDE Artifacts**:
  - `.DS_Store`, `*/.DS_Store`, `**/.DS_Store`, `Thumbs.db`
  - `.idea/`, `.vscode/`, `*.swp`, `*.swo`

### 1.2 Git Tracking Cleanups
- **Database Untracking**: Remove `database/db.sqlite3` from Git tracking index (`git rm --cached database/db.sqlite3`).
- **Legacy Files Deletion Staging**: Confirm removal of previously deleted files from Git index:
  - `Plans/` (Main_menu.md, kapot.md, manager.md, mentor.md)
  - `diagnose_health.py`, `test_remind_callback.py`, `test_user_search.py`
  - `master_key_spec.md`, `security.md`
  - `.env.docker.example`
  - Legacy specs in `docs/superpowers/specs/` (retail tech, cold emails, tab agency)
- **Filesystem Cleanup**: Delete all `.DS_Store` files in the repository.

### 1.3 Environment Template
- Create a sanitized [`.env.example`](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/.env.example) with descriptive placeholders based on `bot/config.py`:
  - `BOT_API_TOKEN`
  - `MAIN_DEVELOPER_ID`
  - `DAYS_TOTAL`
  - `GROQ_API_KEY`
  - `TOKEN_EXPIRY_HOURS`
  - `TOKEN_CLEANUP_INTERVAL_HOURS`
  - `INACTIVE_DAYS_THRESHOLD`
  - `AUTO_REMINDER_INTERVAL_HOURS`
  - `DEBUG`
  - `LOG_TO_FILE`
  - `LOG_FILE_PATH`
  - `DEV_CHAT_ID`

---

## 2. Verification Plan
1. **Ignored Rules Check**: Run `git check-ignore` against target paths:
   - `.agents/`
   - `.agent/`
   - `.env`
   - `database/users.db`
   - `database/db.sqlite3`
   - `security_functions/.master_secret`
   - `logs/bot.log`
2. **Git Status Cleanliness**: Run `git status` to ensure untracked files only contain intended active documents (e.g. `docs/changes/change0508.md`).
