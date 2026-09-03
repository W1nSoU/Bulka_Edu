import aiosqlite
import json
import time
import secrets
import string
from datetime import datetime, timedelta
import pytz
from . import DB_PATH
from bot.config import TIMEZONE
import sqlite3  # Додаємо імпорт для доступу до винятків sqlite3

TOKENS_DB_PATH = DB_PATH.replace("users.db", "tokens.db")

async def init_tokens_db():
    """Ініціалізація бази даних токенів"""
    async with aiosqlite.connect(TOKENS_DB_PATH) as db:
        # Перевіряємо, чи існує таблиця tokens
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tokens'")
        table_exists = await cursor.fetchone()
        
        if not table_exists:
            # Створюємо таблицю з новою структурою, якщо вона не існує
            await db.execute('''
            CREATE TABLE tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE,
                manager_id INTEGER,
                role TEXT,
                city TEXT,
                shop TEXT,
                created_at TIMESTAMP,
                expires_at TIMESTAMP,
                used_by INTEGER DEFAULT NULL,
                used_at TIMESTAMP DEFAULT NULL,
                extra_data TEXT DEFAULT NULL,
                transfer_on_reg INTEGER DEFAULT 0
            )
            ''')
        else:
            # Перевіряємо, чи існує колонка expires_at
            try:
                cursor = await db.execute("SELECT expires_at FROM tokens LIMIT 1")
                await cursor.fetchone()
            except sqlite3.OperationalError:
                await db.execute("ALTER TABLE tokens ADD COLUMN expires_at TIMESTAMP")
                print(f"Додано колонку expires_at до таблиці tokens")
            
            # Перевіряємо used_by
            try:
                cursor = await db.execute("SELECT used_by FROM tokens LIMIT 1")
                await cursor.fetchone()
            except sqlite3.OperationalError:
                await db.execute("ALTER TABLE tokens ADD COLUMN used_by INTEGER DEFAULT NULL")
                print(f"Додано колонку used_by до таблиці tokens")

            # Перевіряємо used_at
            try:
                cursor = await db.execute("SELECT used_at FROM tokens LIMIT 1")
                await cursor.fetchone()
            except sqlite3.OperationalError:
                await db.execute("ALTER TABLE tokens ADD COLUMN used_at TIMESTAMP DEFAULT NULL")
                print(f"Додано колонку used_at до таблиці tokens")

            # Перевіряємо shop
            try:
                cursor = await db.execute("SELECT shop FROM tokens LIMIT 1")
                await cursor.fetchone()
            except sqlite3.OperationalError:
                await db.execute("ALTER TABLE tokens ADD COLUMN shop TEXT DEFAULT NULL")
                print(f"Додано колонку shop до таблиці tokens")

            # Перевіряємо extra_data
            try:
                cursor = await db.execute("SELECT extra_data FROM tokens LIMIT 1")
                await cursor.fetchone()
            except sqlite3.OperationalError:
                await db.execute("ALTER TABLE tokens ADD COLUMN extra_data TEXT DEFAULT NULL")
                print(f"Додано колонку extra_data до таблиці tokens")

            # Перевіряємо transfer_on_reg
            try:
                cursor = await db.execute("SELECT transfer_on_reg FROM tokens LIMIT 1")
                await cursor.fetchone()
            except sqlite3.OperationalError:
                await db.execute("ALTER TABLE tokens ADD COLUMN transfer_on_reg INTEGER DEFAULT 0")
                print(f"Додано колонку transfer_on_reg до таблиці tokens")
                
        await db.commit()
    # print(f"База токенів ініціалізована за шляхом: {TOKENS_DB_PATH}")

async def generate_token(manager_id, role, city=None, shop=None, expires_in_hours=24, extra_data=None, transfer_on_reg=0):
    """
    Створює новий токен для запрошення (стажера, керівника, територіала, наглядача)
    
    Args:
        manager_id: ID керівника/адміна, який запрошує
        role: Роль (посада)
        city: Місто
        shop: Магазин або список магазинів
        expires_in_hours: Час дії токена в годинах
        extra_data: Додаткові дані (dict)
        transfer_on_reg: Чи виконувати авто-переведення після реєстрації (1 або 0)
    """
    # Генеруємо випадковий токен
    alphabet = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(alphabet) for _ in range(16))
    
    # Часові мітки
    now = datetime.now(pytz.timezone(TIMEZONE))
    expires_at = now + timedelta(hours=expires_in_hours)
    
    # Нормалізуємо shop якщо це список
    shop_val = shop
    if isinstance(shop, list):
        shop_val = json.dumps(shop, ensure_ascii=False)
        
    extra_str = None
    if extra_data is not None:
        extra_str = json.dumps(extra_data, ensure_ascii=False) if isinstance(extra_data, dict) else str(extra_data)
    
    try:
        async with aiosqlite.connect(TOKENS_DB_PATH) as db:
            await db.execute(
                '''INSERT INTO tokens 
                   (token, manager_id, role, city, shop, created_at, expires_at, extra_data, transfer_on_reg) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (token, manager_id, role, city, shop_val, now.strftime("%Y-%m-%d %H:%M:%S"), 
                 expires_at.strftime("%Y-%m-%d %H:%M:%S"), extra_str, int(transfer_on_reg or 0))
            )
            await db.commit()
    except Exception as e:
        print(f"Помилка при генерації токена: {e}")
        # Запасний варіант (без shop, якщо стара структура)
        await save_token_data(token, manager_id, role, city)
    
    return token

async def save_token_data(token, manager_id, role, city):
    """Зберігає дані токена (legacy)"""
    async with aiosqlite.connect(TOKENS_DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tokens (token, manager_id, role, city, created_at) VALUES (?, ?, ?, ?, ?)",
            (token, manager_id, role, city, int(time.time()))
        )
        await db.commit()

async def get_token_data(token):
    """Отримує дані по токену, перевіряючи, що він ще дійсний і не використаний"""
    now = datetime.now(pytz.timezone(TIMEZONE))
    
    async with aiosqlite.connect(TOKENS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tokens WHERE token = ?", 
            (token,)
        )
        token_data = await cursor.fetchone()
        
        # Якщо токен не знайдено
        if not token_data:
            return {"status": "not_found"}
            
        # Перетворюємо в словник
        token_data = dict(token_data)
        
        # Якщо токен вже використаний
        if token_data.get("used_by") is not None:
            return {"status": "already_used"}
            
        # Перевіряємо термін дії
        try:
            if "expires_at" in token_data and token_data["expires_at"]:
                expires_at = datetime.fromisoformat(token_data["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = pytz.timezone(TIMEZONE).localize(expires_at)
                    
                if now > expires_at:
                    return {"status": "expired"}
        except (ValueError, TypeError) as e:
            print(f"⚠️ Помилка при розборі дати закінчення токена {token}: {e}")
            
        # Розбираємо extra_data
        extra = {}
        if token_data.get("extra_data"):
            try:
                extra = json.loads(token_data["extra_data"])
            except Exception:
                extra = {}

        # Розбираємо shops
        shop_raw = token_data.get("shop")
        shops_list = []
        if extra.get("shops") and isinstance(extra["shops"], list):
            shops_list = extra["shops"]
        elif shop_raw:
            try:
                parsed = json.loads(shop_raw)
                if isinstance(parsed, list):
                    shops_list = parsed
                else:
                    shops_list = [str(parsed)]
            except Exception:
                shops_list = [shop_raw]

        transfer_flag = int(token_data.get("transfer_on_reg") or 0)
        if not transfer_flag and extra.get("transfer_on_reg"):
            transfer_flag = 1

        # Токен валідний, повертаємо дані
        return {
            "status": "ok",
            "manager_id": token_data["manager_id"],
            "role": token_data.get("role", "Стажер"),
            "city": token_data.get("city", "Не вказано"),
            "shop": shop_raw,
            "shops": shops_list,
            "extra_data": extra,
            "transfer_on_reg": transfer_flag
        }

async def use_token(token, user_id):
    """
    Позначає токен як використаний
    
    Args:
        token: Токен для позначення
        user_id: ID користувача, який використав токен
        
    Returns:
        bool: True, якщо токен успішно позначено, False в інакше
    """
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(TOKENS_DB_PATH) as db:
        # Перевіряємо, чи токен ще не використаний
        cursor = await db.execute(
            "SELECT used_by FROM tokens WHERE token = ?", 
            (token,)
        )
        token_data = await cursor.fetchone()
        
        if not token_data:
            return False  # Токен не існує
            
        if token_data[0] is not None:
            return False  # Токен вже використаний
            
        # Позначаємо токен як використаний
        await db.execute(
            "UPDATE tokens SET used_by = ?, used_at = ? WHERE token = ?",
            (user_id, now, token)
        )
        await db.commit()
        return True

async def get_token_stats() -> dict:
    """Отримує статистику по токенах: активні, використані, прострочені."""
    now = datetime.now(pytz.timezone(TIMEZONE))
    
    async with aiosqlite.connect(TOKENS_DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM tokens")
        total_tokens = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM tokens WHERE used_by IS NOT NULL")
        used_tokens = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM tokens WHERE used_by IS NULL AND expires_at > ?",
                                  (now.strftime("%Y-%m-%d %H:%M:%S"),))
        active_tokens = (await cursor.fetchone())[0]
        
        expired_tokens = total_tokens - used_tokens - active_tokens
        
        return {
            "total": total_tokens,
            "active": active_tokens,
            "used": used_tokens,
            "expired": expired_tokens
        }

async def cleanup_expired_tokens() -> int:
    """Видаляє прострочені та невикористані токени з бази даних."""
    now = datetime.now(pytz.timezone(TIMEZONE))
    
    async with aiosqlite.connect(TOKENS_DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM tokens WHERE expires_at < ? AND used_by IS NULL",
            (now.strftime("%Y-%m-%d %H:%M:%S"),)
        )
        await db.commit()
        return cursor.rowcount

