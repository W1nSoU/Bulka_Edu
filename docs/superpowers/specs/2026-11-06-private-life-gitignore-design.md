# Design Spec: Private Life & Sensitive Assets Git Ignore

**Date:** 2026-11-06  
**Status:** Approved by user  
**Topic:** Exclusion of private life data, personal AI memory, contracts, resumes, and YouTube assets from Git tracking.

---

## 1. Context & Goal

The workspace contains sensitive personal files alongside open-source/project code for Bulka Edu:
- Personal AI memory profiles, daily logs, and Life OS infrastructure (`AI/`, `AI/memory/danik_master_profile.md`).
- Commercial contracts and agreements (e.g. `Договір_TAB_Edu_SaaS.docx`).
- Career documents, resumes, and client/company test tasks (e.g. `Manimama_Test_Danik.docx`).
- YouTube storytelling media production plans, scripts, and audio assets (`Richard still alive`).

Goal: Ensure all current and future sensitive personal files are ignored by Git, and safely remove previously indexed private files from the Git tracking tree without deleting local disk copies.

---

## 2. Changes to `.gitignore`

Add the following structured blocks to `.gitignore`:

```gitignore
# ==========================================
# Private Life, Personal AI & Memory
# ==========================================
AI/
.agents/
.agent/
private_server/
*danik*
*Danik*

# ==========================================
# Contracts, Legal & Commercial Agreements
# ==========================================
*Договір*
*договір*
*contract*
*Contract*
*agreement*
*Agreement*
*.docx
*.pdf

# ==========================================
# Career, Tests & Resumes
# ==========================================
*Manimama*
*manimama*
*Resume*
*resume*
*CV*
*cv*

# ==========================================
# YouTube Production & Creative Media
# ==========================================
*youtube*
*YouTube*
*Richard*
*richard*
docs/superpowers/plans/*episode*
docs/superpowers/specs/*youtube*
*.mp3
*.wav
*.ogg
*.mp4
*.mov
```

---

## 3. Git Index Cache Purge

Run:
```bash
git rm --cached AI/memory/danik_master_profile.md
git rm --cached Manimama_Test_Danik.docx 2>/dev/null || true
```

---

## 4. Verification

1. Verify `git status` shows no tracked changes to `AI/memory/danik_master_profile.md` or any personal docs.
2. Confirm files remain physically intact on Mac disk.
3. Commit updated `.gitignore`.
