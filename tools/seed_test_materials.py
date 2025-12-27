#!/usr/bin/env python3
"""
Заповнює таблицю materials реалістичними даними для всіх ролей і днів 1-7.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import List

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(ROOT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

import aiosqlite

from bot.constants import AVAILABLE_ROLES
from database import DB_PATH

DAYS_RANGE = range(1, 8)

DAY_CONTENT = {
    1: {
        "title": "Вітання та перший контакт",
        "info": "Як {role} ти зустрічаєш гостя з теплою посмішкою та словами "
                "«Доброго дня! Чим можу допомогти?». Відкриті жести та щирий погляд задають тон усій розмові.",
        "comic": "У коміксі Булка демонструє, як усміхнений продавець нахиляється на рівень очей клієнта і запрошує до діалогу.",
        "video": "Кадри нагадують про правило двох секунд: контакт очима, вітання та уточнення потреби — усе з позитивним настроєм.",
    },
    2: {
        "title": "Асортимент і підказки",
        "info": "{role} знає, де лежить кожна позиція, але якщо сумніваєшся — прямо скажи, що уточниш, і миттєво звернись до колеги. "
                "Клієнт цінує чесність і швидкий пошук відповіді.",
        "comic": "Комікс показує, як Булка ставить лапку до підборіддя, а потім \"дзеркалить\" відповідь старшого продавця.",
        "video": "Навчальне відео демонструє техніку трьох питань: що потрібно, скільки часу є на вибір і яка важлива характеристика.",
    },
    3: {
        "title": "Каса та обіг грошей",
        "info": "Перед роботою {role} перевіряє касу: чистота, наявність розмінних грошей, справність чекера. "
                "Обовʼязково озвучуй суму й підтверджуй видачу решти.",
        "comic": "На кадрах Булка рахує купюри вголос і пояснює клієнту кожен крок, щоб уникнути непорозумінь.",
        "video": "Відео грунтовно нагадує про безпеку: не відкривай касу без клієнта, блокуй робоче місце, зберігай чеки.",
    },
    4: {
        "title": "Чистота й порядок",
        "info": "{role} підтримує зал охайним: витирає крихти одразу, вирівнює полички, оновлює цінники. "
                "Клієнт помічає будь-який безлад, тому треба діяти відразу.",
        "comic": "Комікс демонструє, як Булка з мітлою відганяє \"пилюкових монстрів\" від стелажів.",
        "video": "Відео показує маршрут годинного обходу: вхід, гаряча зона, каса, склад, і повернення з чек-листом виконаних дій.",
    },
    5: {
        "title": "Командна комунікація",
        "info": "Щодня {role} ділиться коротким звітом: що продається краще, які питання задають клієнти, що закінчується. "
                "Пряме й доброзичливе спілкування економить час усім.",
        "comic": "Комікс із двома котами-продавцями показує передачу зміни й дружній «дай пʼять».",
        "video": "Відео демонструє ранковий брифінг: пʼять хвилин, конкретні задачі й підтримка один одного.",
    },
    6: {
        "title": "Конфлікти з клієнтом",
        "info": "Перш ніж відповісти, {role} слухає без перебивань, перефразовує проблему й пропонує варіанти рішення. "
                "Спокійний тон і вдячність за зворотний звʼязок знімають напругу.",
        "comic": "Булка глибоко вдихає, рахує до трьох і лише потім відповідає незадоволеному гостю — саме так зберігаємо повагу.",
        "video": "Відео показує техніку S.A.R.A: вислухай (Stay), вибачся (Apologize), виріши (Resolve), підтвердь (Acknowledge).",
    },
    7: {
        "title": "Підсумок та стандарти бренду",
        "info": "Фінальний день нагадує {role}, що бренд — це дрібниці: форма, охайність, передача справ наступній зміні, "
                "активний інтерес до клієнтів.",
        "comic": "Комікс святкує завершення навчального тижня: вся команда Булки обіймається від відчуття виконаної роботи.",
        "video": "Підсумкове відео збирає найкращі практики тижня та мотивує планувати нові цілі й особистий розвиток.",
    },
}


async def clear_materials(db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM materials")
    await db.commit()


def _slugify_role(role: str) -> str:
    slug = re.sub(r"[^\w]+", "-", role.lower()).strip("-")
    return slug or "role"


def build_records() -> List[tuple]:
    records: List[tuple] = []
    for role in AVAILABLE_ROLES:
        role_slug = _slugify_role(role)
        for day in DAYS_RANGE:
            data = DAY_CONTENT[day]

            info_title = f"День {day}: {data['title']}"
            info_content = data["info"].format(role=role, day=day)
            records.append((role, day, "info", info_title, info_content, None, 0))

            comic_title = f"Комікс · {data['title']}"
            comic_content = data["comic"].format(role=role, day=day)
            comic_url = f"https://example.com/comic/{role_slug}/{day}.jpg"
            records.append((role, day, "comic", comic_title, comic_content, comic_url, 1))

            video_title = f"Відео · {data['title']}"
            video_content = data["video"].format(role=role, day=day)
            video_url = f"https://example.com/video/{role_slug}/{day}"
            records.append((role, day, "video", video_title, video_content, video_url, 2))
    return records


async def seed_materials():
    print(f"📚 Сидимо materials у БД: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        await clear_materials(db)
        records = build_records()
        await db.executemany(
            """
            INSERT INTO materials (role, day, content_type, title, content, resource_url, order_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        await db.commit()
    print(f"✅ Додано {len(records)} матеріалів для {len(AVAILABLE_ROLES)} ролей, 7 днів кожній.")


async def main():
    await seed_materials()


if __name__ == "__main__":
    asyncio.run(main())
