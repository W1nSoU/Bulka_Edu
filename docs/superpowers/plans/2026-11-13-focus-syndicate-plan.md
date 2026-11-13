# FOCUS SYNDICATE: Implementation Plan

> **Architecture Spec:** [2026-11-13-focus-syndicate-design.md](../specs/2026-11-13-focus-syndicate-design.md)  
> **Target Project Directory:** `/Users/daniildusinskij/All/Dev/Focus_Syndicate`  
> **Goal:** Побудувати локальну систему (Telegram Bot + Bot API 10.4 HTML Widgets + FastAPI WebSocket `/screen`, `/admin`, `/board` + SQLite WAL + повні pytest-тести).

---

### Task 1: Project Skeleton & Environment (`../Focus_Syndicate`)
- Створити структуру `db/`, `engine/`, `bot/`, `web/static/`, `tests/`.
- Скопіювати локальний `lightweight-charts.js` у `web/static/lightweight-charts.js`.
- Налаштувати `requirements.txt`, `.env.example`, `config.py`, `venv` (Python 3.9+ сумісність із `from __future__ import annotations`).

### Task 2: SQLite WAL Persistence (`db/sqlite.py`)
- Таблиці: `game_state`, `syndicates`, `players`, `pitch_sessions`, `positions`, `candles`, `synergy_resources`, `synergy_alliances`, `duel_sessions`, `duel_bets`, `ledger`.
- Атомарні транзакції (`BEGIN IMMEDIATE`) для реєстрації гравців, створення/вступу в синдикати, ролей, переказів і збереження історії свічок.

### Task 3: Market & Game Engine (`engine/market.py`, `engine/game.py`)
- `MarketEngine`: старт нової сесії з `P₀ = 1.000`, 1-секундний генератор OHLC-свічок, ціновий вплив від обсягу `√(M * L)`, ізольована маржа (`100k / 250k / 500k / ALL-IN` × `x1 / x3 / x5 / x10`), формули `PnL` та автоліквідація (`PnL <= -M`), `Margin Call ВГОРУ / ВНИЗ` (`±35%`), пауза/відновлення.
- `GameEngine`: state machine (`LOBBY → PRE_MARKET_LOCK → TRADING → SYNERGY → DUEL → FINALE`), сума капіталів гравців у синдикаті, застава `500k` + `2%` роялті + `1M` премія засновника, Синергія (+1M / -200k), Split or Steal + Polymarket (Parimutuel), Headhunting («Купівля людини» за `1.5M FD`).

### Task 4: Bot API 10.4 Widgets & Telegram Handlers (`bot/`)
- `bot/widgets_api.py`: клієнт `sendWidget`, `editMessageWidgetData`, `answerWidgetQuery`, throttling-черга для оновлення живого PnL раз на 2.5с.
- `bot/templates.py`: мініфіковані HTML-шаблони (`< 2.5 KB gzip` кожен, перевіряється тестом!): Lock-банер, Hub/Синдикат (створення, QR/код, ролі), Trading-віджет (LONG/SHORT, маржа, плече, живий PnL + кнопка закриття), Synergy-віджет, Duel/Polymarket-віджет.
- `bot/handlers.py` & `bot/admin_handlers.py`: роутинг `/start` (`ADMIN_TG_IDS` -> одразу адмінка, гість -> реєстрація/QR/віджет), генерація QR-зображень, `widget_query` диспетчер, `/legacy` inline-fallback.

### Task 5: Web Server & UI (`web/app.py`, `web/static/`)
- `/screen`: **суто білий TradingView 1с свічний графік (`100vw × 100vh`)**, старт із `1.000`, обсяги знизу, OHLC шапка, bid/ask, UTC+2 час, WebSocket live updates і чистий перезапуск при виборі нового спікера або F5.
- `/admin`: **окрема вкладка** пульта адміністратора (Етап 1 Lock, вибір команди+спікера, Стоп/Старт, Margin Call ↑/↓, `LONG WIN`/`SHORT WIN`, «Купівля людини», Раунди 2/3/4, кнопка відкриття `/screen` і `/board`).
- `/board`: **окрема вкладка проектора** (QR входу, криза Раунду 2, дуель `Split or Steal`, фінальний лідерборд).

### Task 6: Entrypoint & Verification (`main.py`, `tests/`)
- `main.py`: єдиний `asyncio` цикл (`init_db` + `uvicorn` + custom `getUpdates` poller із `widget_query` + `aiogram` Dispatcher + `1s` tick loop).
- `tests/`: повне покриття (`test_market.py`, `test_rounds.py`, `test_widgets_and_api.py`, `test_load.py` для 40 одночасних гравців) + реальна перевірка `/screen` і `/admin` у браузері.
