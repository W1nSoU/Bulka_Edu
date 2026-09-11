from __future__ import annotations
import os
import hmac
import hashlib
import json
import logging
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, Any, List

import pytz
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bot.config import API_TOKEN, TIMEZONE, DEBUG, WEB_SERVER_HOST, WEB_SERVER_PORT
from database.attestation import (
    get_active_wave,
    get_questions_for_role,
    get_user_latest_attempt,
    start_user_attempt,
    submit_user_attempt,
    add_participants_batch
)
from database.users import get_user_details
from database.managers import get_manager_by_uid

logger = logging.getLogger(__name__)

# Створюємо екземпляр FastAPI
app = FastAPI(title="BULKA Attestation Mini App API", docs_url=None, redoc_url=None)

# Дозволяємо CORS для безшовного відкриття в Telegram WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/attestation"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Глобальне посилання на Aiogram Bot для відправки нотифікацій
_bot_instance = None

def set_bot_instance(bot):
    global _bot_instance
    _bot_instance = bot


def validate_telegram_init_data(init_data: str, bot_token: str = API_TOKEN) -> Optional[Dict[str, Any]]:
    """
    Валідує криптографічний підпис Telegram WebApp initData (HMAC-SHA256).
    Повертає словник даних користувача або None, якщо підпис невалідний.
    """
    if not init_data:
        return None

    # Режим розробника для локального тестування у браузері
    if DEBUG and init_data.startswith("debug_user_id="):
        try:
            uid = int(init_data.split("=")[1])
            return {"id": uid, "first_name": "Тестовий", "last_name": "Користувач", "username": "testuser"}
        except Exception:
            return None

    try:
        parsed = urllib.parse.parse_qs(init_data, keep_blank_values=True)
        if "hash" not in parsed:
            return None

        received_hash = parsed["hash"][0]

        # Формуємо рядок перевірки
        data_pairs = []
        for k, v in parsed.items():
            if k != "hash":
                data_pairs.append(f"{k}={v[0]}")
        data_pairs.sort()
        data_check_string = "\n".join(data_pairs)

        # Telegram secret key = HMAC-SHA256(b"WebAppData", bot_token)
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if hmac.compare_digest(calc_hash, received_hash):
            user_str = parsed.get("user", ["{}"])[0]
            return json.loads(user_str)
        else:
            logger.warning(f"HMAC mismatch: calc={calc_hash}, recv={received_hash}")
            if DEBUG and "user" in parsed:
                logger.info("DEBUG=true: allowing user despite HMAC mismatch")
                return json.loads(parsed["user"][0])
    except Exception as e:
        logger.error(f"Помилка валідації initData: {e}")

    return None


# -------------------------------------------------------------
# Pydantic моделі запитів
# -------------------------------------------------------------

class InitRequest(BaseModel):
    init_data: str


class SubmitRequest(BaseModel):
    init_data: str
    attempt_id: int
    answers: Dict[str, int] # {question_id: selected_option (1..4)}


# -------------------------------------------------------------
# API Ендпоінти
# -------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.post("/attestation/api/init")
async def api_init_attestation(req: InitRequest):
    """
    Ініціалізація сесії атестації для працівника:
    1. Перевірка Telegram initData
    2. Перевірка наявності активної хвилі
    3. Перевірка належності до магазинів хвилі
    4. Отримання або запуск спроби тестування
    5. Повернення питань (БЕЗ правильних відповідей!)
    """
    logger.info(f"[/attestation/api/init] Received init request (len={len(req.init_data)})")
    user_data = validate_telegram_init_data(req.init_data)
    if not user_data or not user_data.get("id"):
        logger.warning(f"[/attestation/api/init] Unauthorized initData: {req.init_data[:50]}...")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"status": "locked", "reason": "unauthorized", "message": "Неавторизований доступ. Відкрийте застосунок через Telegram."}
        )

    user_id = user_data["id"]
    logger.info(f"[/attestation/api/init] User authenticated: ID={user_id}")

    # 1. Перевірка активної хвилі
    wave = await get_active_wave()
    if not wave:
        return {
            "status": "locked",
            "reason": "no_active_wave",
            "message": "Наразі немає активної корпоративної атестації 🥐"
        }

    # 2. Визначаємо посаду та магазин користувача
    role_name = None
    shop_name = None
    full_name = f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()
    is_manager = 0
    wave_shops = wave.get("shops", [])

    # Перевірка в базі керівників
    manager = await get_manager_by_uid(user_id)
    if manager and manager.get("status") != "fired":
        role_name = "Керівник"
        is_manager = 1
        full_name = manager.get("full_name") or manager.get("name") or full_name
        # Беремо закріплені магазини
        shops_list = manager.get("shops", [])
        if isinstance(shops_list, str):
            try:
                shops_list = json.loads(shops_list)
            except Exception:
                shops_list = [shops_list]
        elif not isinstance(shops_list, list):
            shops_list = []

        # Знаходимо магазин керівника, який бере участь у хвилі
        for s in shops_list:
            if s in wave_shops:
                shop_name = s
                break
        if not shop_name and len(shops_list) > 0:
            shop_name = shops_list[0]

    # Якщо не знайдено в managers — шукаємо в базі користувачів (users.db)
    if not role_name:
        user_db = await get_user_details(user_id)
        if user_db:
            if user_db.get("role") == "Керівник":
                role_name = "Керівник"
                is_manager = 1
                shop_name = user_db.get("shop")
                full_name = user_db.get("full_name") or full_name
            elif user_db.get("status") != "Працівник":
                return {
                    "status": "locked",
                    "reason": "intern",
                    "message": "Піврічна атестація проводиться лише для діючих працівників та керівників магазинів 🎓"
                }
            else:
                role_name = user_db.get("role")
                shop_name = user_db.get("shop")
                full_name = user_db.get("full_name") or full_name

    if not role_name or not shop_name:
        return {
            "status": "locked",
            "reason": "profile_incomplete",
            "message": "Ваш профіль або магазин не налаштовано в системі. Зверніться до наставника чи адміністратора."
        }

    # 3. Перевірка чи включено магазин користувача у хвилю
    wave_shops = wave.get("shops", [])
    if shop_name not in wave_shops:
        return {
            "status": "locked",
            "reason": "shop_not_in_wave",
            "message": f"Магазин '{shop_name}' не бере участі в поточній хвилі атестації."
        }

    # Автоматично реєструємо як учасника хвилі (якщо ще не додано)
    await add_participants_batch(wave["id"], [{
        "user_id": user_id,
        "full_name": full_name,
        "role_name": role_name,
        "shop_name": shop_name,
        "is_manager": is_manager
    }])

    # 4. Перевірка спроб тестування
    latest_attempt = await get_user_latest_attempt(wave["id"], user_id)

    if latest_attempt and latest_attempt["status"] in ("passed", "failed") and latest_attempt["can_retake"] == 0:
        return {
            "status": "completed",
            "attempt_status": latest_attempt["status"],
            "score": latest_attempt["score"],
            "max_score": latest_attempt["max_score"],
            "score_pct": latest_attempt["score_pct"],
            "finished_at": latest_attempt["finished_at"],
            "shop_name": shop_name,
            "role_name": role_name,
            "user_name": full_name,
            "wave_title": wave["title"]
        }

    # Якщо спроба триває — перевіряємо час
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    duration_minutes = wave.get("duration_minutes", 20)

    if latest_attempt and latest_attempt["status"] == "in_progress":
        attempt = latest_attempt
        # Рахуємо залишок часу
        started_at = attempt.get("started_at")
        if started_at:
            try:
                start_dt = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                start_dt = tz.localize(start_dt) if start_dt.tzinfo is None else start_dt
                elapsed_sec = int((now - start_dt).total_seconds())
                remaining_sec = (duration_minutes * 60) - elapsed_sec
            except Exception:
                remaining_sec = duration_minutes * 60
        else:
            remaining_sec = duration_minutes * 60

        # Якщо час вичерпано — авто-фініш
        if remaining_sec <= 0:
            saved_answers = json.loads(attempt.get("answers_json") or "{}")
            final_attempt = await submit_user_attempt(attempt["id"], saved_answers)
            return {
                "status": "completed",
                "attempt_status": final_attempt["status"],
                "score": final_attempt["score"],
                "max_score": final_attempt["max_score"],
                "score_pct": final_attempt["score_pct"],
                "finished_at": final_attempt["finished_at"],
                "shop_name": shop_name,
                "role_name": role_name,
                "user_name": full_name,
                "wave_title": wave["title"]
            }
    else:
        # Стартуємо нову спробу
        attempt = await start_user_attempt(wave["id"], user_id, role_name, shop_name)
        remaining_sec = duration_minutes * 60

    # 5. Отримуємо питання для ролі (суворо БЕЗ correct_option та explanation)
    raw_questions = await get_questions_for_role(role_name)
    if not raw_questions:
        return {
            "status": "locked",
            "reason": "no_questions",
            "message": f"Банк запитань для посади '{role_name}' наразі наповнюється. Спробуйте пізніше."
        }

    questions_payload = []
    for q in raw_questions:
        options = [q["option_1"], q["option_2"]]
        if q.get("option_3"):
            options.append(q["option_3"])
        if q.get("option_4"):
            options.append(q["option_4"])

        questions_payload.append({
            "id": q["id"],
            "question_text": q["question_text"],
            "options": options,
            "points": q["points"]
        })

    saved_answers = json.loads(attempt.get("answers_json") or "{}")

    return {
        "status": "ready",
        "attempt_id": attempt["id"],
        "wave_title": wave["title"],
        "role_name": role_name,
        "shop_name": shop_name,
        "user_name": full_name,
        "duration_minutes": duration_minutes,
        "remaining_seconds": max(0, remaining_sec),
        "passing_score_pct": wave.get("passing_score_pct", 80),
        "questions": questions_payload,
        "saved_answers": saved_answers
    }


@app.post("/attestation/api/submit")
async def api_submit_attestation(req: SubmitRequest):
    """
    Приймає фінальні відповіді користувача та підраховує підсумковий результат.
    """
    user_data = validate_telegram_init_data(req.init_data)
    if not user_data or not user_data.get("id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")

    user_id = user_data["id"]

    try:
        final_attempt = await submit_user_attempt(req.attempt_id, req.answers)
    except Exception as e:
        logger.error(f"Помилка збереження результату атестації: {e}")
        raise HTTPException(status_code=500, detail="Помилка збереження відповідей")

    # Надсилаємо персональне сповіщення в бот через aiogram
    if _bot_instance:
        try:
            verdict_emoji = "🎉" if final_attempt["status"] == "passed" else "⏳"
            verdict_text = "Атестацію успішно складено!" if final_attempt["status"] == "passed" else "Атестацію не складено."
            msg = (
                f"{verdict_emoji} <b>Результати атестації</b>\n\n"
                f"👤 <b>Співробітник:</b> {user_data.get('first_name', '')}\n"
                f"🏪 <b>Магазин:</b> {final_attempt['shop_name']}\n"
                f"💼 <b>Посада:</b> {final_attempt['role_name']}\n"
                f"📊 <b>Результат:</b> {final_attempt['score']} з {final_attempt['max_score']} балів ({final_attempt['score_pct']}%)\n\n"
                f"📌 <b>Вердикт:</b> <b>{verdict_text}</b>"
            )
            await _bot_instance.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не вдалося надіслати підсумкове повідомлення користувачу {user_id}: {e}")

    return {
        "status": "ok",
        "attempt_status": final_attempt["status"],
        "score": final_attempt["score"],
        "max_score": final_attempt["max_score"],
        "score_pct": final_attempt["score_pct"],
        "shop_name": final_attempt["shop_name"],
        "duration_seconds": final_attempt["duration_seconds"]
    }


# -------------------------------------------------------------
# Сервірування статичних файлів Mini App
# -------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "attestation")
os.makedirs(STATIC_DIR, exist_ok=True)

# Монтуємо роздачу статики
app.mount("/attestation", StaticFiles(directory=STATIC_DIR, html=True), name="attestation_static")


async def run_web_server_async(bot=None):
    """Запускає веб-сервер у поточному асинхронному циклі."""
    import uvicorn
    if bot:
        set_bot_instance(bot)

    config = uvicorn.Config(
        app=app,
        host=WEB_SERVER_HOST,
        port=WEB_SERVER_PORT,
        log_level="warning" if not DEBUG else "info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    logger.info(f"🌐 FastAPI Web Server запущено на http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}/attestation")
    await server.serve()
