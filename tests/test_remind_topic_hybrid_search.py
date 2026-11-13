"""Tests for hybrid retrieval, SQLite embedding cache, 2-stage network search, and UI fixes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosqlite

from bot.services.knowledge_chunker import (
    UNASSIGNED_ROLE,
    build_deduplicated_chunks,
    extract_clean_text,
    split_into_chunks,
)
from bot.services.openai_ai import NO_ANSWER_MARKER, answer_remind_topic
from bot.services.semantic_search import (
    hybrid_search_chunks,
    reset_semantic_search_index,
    sync_knowledge_index,
)
from database.knowledge_chunks import get_all_knowledge_chunks, init_knowledge_chunks_db
from database.positions import get_searchable_roles


async def _create_test_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                day INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                title TEXT,
                content TEXT,
                resource_url TEXT,
                order_index INTEGER DEFAULT 0,
                is_enabled BOOLEAN DEFAULT 1,
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                days_count INTEGER DEFAULT 5,
                territorial_type TEXT DEFAULT 'ТЗ',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()
    await init_knowledge_chunks_db(db_path)


class _FakeEmbeddingsAPI:
    def __init__(self, vector_fn=None):
        self.calls: list[list[str]] = []
        self.vector_fn = vector_fn or (lambda txt: [1.0, 0.0, 0.0, 0.0])

    async def create(self, model: str, input: list[str]):
        self.calls.append(list(input))
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=self.vector_fn(text)) for text in input]
        )


class _FakeChatCompletionsAPI:
    def __init__(self, handler):
        self.calls: list[dict] = []
        self.handler = handler

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.handler(kwargs, len(self.calls))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )


class _FakeOpenAIClient:
    def __init__(self, vector_fn=None, chat_handler=None):
        self.embeddings = _FakeEmbeddingsAPI(vector_fn=vector_fn)
        self.chat = SimpleNamespace(
            completions=_FakeChatCompletionsAPI(
                chat_handler or (lambda kwargs, idx: "Офіційна відповідь з інструкції [День 1].")
            )
        )


class _FailingOpenAIClient:
    def __init__(self):
        async def _boom(*args, **kwargs):
            raise RuntimeError("OpenAI upstream timeout")

        self.embeddings = SimpleNamespace(create=_boom)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=_boom))


class _FakeFSMContext:
    def __init__(self, initial=None):
        self.data = dict(initial or {})
        self.state = None
        self.cleared = False

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self.cleared = True
        self.data = {}
        self.state = None


class TestKnowledgeChunker(unittest.TestCase):
    def test_extract_clean_text_strips_photo_ids_and_ignores_non_text(self):
        payload = json.dumps(
            [
                {"text": "❗️Товар категорії «Алкоголь» ЗАБОРОНЕНО списувати.", "photo": "AgACAgIAAxkBAAIB1"},
                {"photo": "AgACAgIAAxkBAAIB2"},
                {"text": "Другий абзац правила.", "photo": ""},
            ],
            ensure_ascii=False,
        )
        cleaned = extract_clean_text(payload, content_type="text")
        self.assertIn("ЗАБОРОНЕНО списувати", cleaned)
        self.assertIn("Другий абзац правила", cleaned)
        self.assertNotIn("AgACAg", cleaned)
        self.assertNotIn('"photo"', cleaned)

        self.assertEqual(extract_clean_text('{"q":"1"}', content_type="test"), "")
        self.assertEqual(extract_clean_text('["file1"]', content_type="photo_files"), "")
        self.assertEqual(extract_clean_text('["vid1"]', content_type="video_files"), "")

    def test_split_into_chunks_respects_size_and_overlap(self):
        paragraphs = [f"Абзац {i}. Це детальна інструкція для працівника магазину про порядок дій #{i}." * 3 for i in range(1, 10)]
        long_text = "\n\n".join(paragraphs)
        chunks = split_into_chunks(long_text, target_chars=750, max_chars=900, overlap_chars=120)
        self.assertGreater(len(chunks), 2)
        for ch in chunks:
            self.assertLessEqual(len(ch), 950)
        # Verify tail of chunk 0 overlaps into chunk 1
        tail_words = chunks[0].split()[-4:]
        self.assertTrue(any(w in chunks[1] for w in tail_words))

    def test_build_deduplicated_chunks_combines_identical_roles_and_labels_empty_role(self):
        shared_json = json.dumps([{"text": "Алкоголь заборонено списувати при пошкодженні покупцем."}], ensure_ascii=False)
        materials = [
            {"id": 1, "role": "Старший продавець", "day": 1, "content_type": "text", "title": "День 1 — Текст", "content": shared_json},
            {"id": 4, "role": "Продавець-консультант (каса)", "day": 1, "content_type": "text", "title": "День 1 — Текст", "content": shared_json},
            {"id": 99, "role": "", "day": 1, "content_type": "text", "title": "Загальне", "content": "Спільне правило без призначеної ролі для мережі."},
        ]
        chunks = build_deduplicated_chunks(materials)
        self.assertEqual(len(chunks), 2)
        alcohol_chunk = next(c for c in chunks if "Алкоголь" in c["chunk_text"])
        roles_in_sources = {s["role"] for s in alcohol_chunk["sources"]}
        self.assertEqual(roles_in_sources, {"Старший продавець", "Продавець-консультант (каса)"})

        unassigned = next(c for c in chunks if "без призначеної ролі" in c["chunk_text"])
        self.assertEqual(unassigned["sources"][0]["role"], UNASSIGNED_ROLE)
        self.assertEqual(unassigned["sources"][0]["display_role"], "Загальні матеріали")


class TestHybridSearchAndSqliteCache(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_users.db")
        await _create_test_db(self.db_path)
        await reset_semantic_search_index()

    async def asyncTearDown(self):
        await reset_semantic_search_index()
        self.tmp_dir.cleanup()

    async def test_incremental_embedding_cache_and_cleanup(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Касир", 1, "День 1", "Правило 1: відкриття касової зміни о 07:30."),
            )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Пекар", 1, "День 1", "Правило 2: випікання багетів при температурі 220 градусів."),
            )
            await db.commit()

        fake_client = _FakeOpenAIClient()
        chunks_v1 = await sync_knowledge_index(compute_embeddings=True, db_path=self.db_path, client=fake_client)
        self.assertEqual(len(chunks_v1), 2)
        self.assertEqual(len(fake_client.embeddings.calls), 1)
        self.assertEqual(len(fake_client.embeddings.calls[0]), 2)

        # Second sync with unchanged materials -> zero OpenAI calls.
        await sync_knowledge_index(compute_embeddings=True, db_path=self.db_path, client=fake_client)
        self.assertEqual(len(fake_client.embeddings.calls), 1)

        # Update 1 material and delete the other -> only the new text gets embedded; deleted disappears.
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE materials SET content = ?, updated_at = datetime('now', '+5 seconds') WHERE role = 'Касир'",
                ("Правило 1 оновлене: відкриття каси о 08:00.",),
            )
            await db.execute("DELETE FROM materials WHERE role = 'Пекар'")
            await db.commit()

        chunks_v2 = await sync_knowledge_index(compute_embeddings=True, db_path=self.db_path, client=fake_client)
        self.assertEqual(len(chunks_v2), 1)
        self.assertEqual(len(fake_client.embeddings.calls), 2)
        self.assertEqual(fake_client.embeddings.calls[1], ["Правило 1 оновлене: відкриття каси о 08:00."])
        stored_rows = await get_all_knowledge_chunks(self.db_path)
        self.assertEqual(len(stored_rows), 1)

    async def test_alcohol_writeoff_day1_and_complete_rc_recall_without_serce(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Real Day 1 alcohol rule inside JSON with photo noise + Day 4 distractor.
            day1_json = json.dumps(
                [
                    {
                        "text": "❗️Товар категорії «Алкоголь» ЗАБОРОНЕНО списувати. Він має бути проплачений.",
                        "photo": "AgACAgIAAxkBA111",
                    }
                ],
                ensure_ascii=False,
            )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Старший продавець", 1, "День 1 — Текст", day1_json),
            )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Старший продавець", 4, "День 4 — Текст", "Викладка алкогольних напоїв та пива на полицях залу."),
            )
            # 14 distinct chunks containing 'РЦ' (> TOP_FULL_CHUNKS=10) + 1 false-friend 'серце'.
            for i in range(1, 15):
                long_prefix = f"Загальний блок #{i} про порядок роботи магазину, маркування товару та графік. " * 6
                await db.execute(
                    "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                    (f"Роль {i}", (i % 5) + 1, f"Інструкція {i}", f"{long_prefix}\n\nРечення про РЦ номер {i}: замовлення на РЦ відправляємо до 14:00."),
                )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Роль Шум", 1, "Медпункт", "Від щирого серця бажаємо гарної зміни та турботи про здоров'я."),
            )
            await db.commit()

        # Deliberately bias embeddings AWAY from Day 1 & RC to prove hybrid lexical + exact scan wins!
        def biased_vec(text: str) -> list[float]:
            if "Викладка" in text or "серця" in text:
                return [1.0, 0.0, 0.0]
            if "Списування алкоголю" in text or text == "РЦ":
                return [0.9, 0.1, 0.0]
            return [0.0, 1.0, 0.0]

        fake_client = _FakeOpenAIClient(vector_fn=biased_vec)
        res_alc = await hybrid_search_chunks(
            query="Списування алкоголю",
            role_filter="Старший продавець",
            scope="role",
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertTrue(res_alc["has_relevant_match"])
        self.assertIn("ЗАБОРОНЕНО списувати", res_alc["results"][0]["excerpt"])

        res_rc = await hybrid_search_chunks(
            query="РЦ",
            role_filter=None,
            scope="global",
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertTrue(res_rc["has_relevant_match"])
        returned_texts = "\n".join(r["excerpt"] for r in res_rc["results"])
        for i in range(1, 15):
            self.assertIn(f"Речення про РЦ номер {i}", returned_texts)
        self.assertNotIn("щирого серця", returned_texts)

    async def test_two_stage_search_respects_own_role_first_then_network_fallback(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                (
                    "Продавець-консультант (каса)",
                    1,
                    "День 1",
                    "Касове обслуговування: привітати покупця, видати чек, запропонувати пакет.",
                ),
            )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                (
                    "Продавець-консультант (каса)",
                    2,
                    "День 2",
                    "Графік поставок: машина з РЦ приїжджає вранці.",
                ),
            )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                (
                    "Продавець-приймальник",
                    3,
                    "День 3",
                    "Повернення на РЦ: прострочений або бракований товар оформлюємо актом повернення на РЦ до вівторка.",
                ),
            )
            await db.commit()

        # 1) Role with 0 materials ('Комплектувальник-приймальник') automatically searches entire network.
        def rc_chat_handler(kwargs, call_idx):
            sys_prompt = kwargs["messages"][0]["content"]
            user_q = kwargs["messages"][1]["content"]
            if "Космодром" in user_q:
                return NO_ANSWER_MARKER
            if "актом повернення на РЦ" in sys_prompt:
                return "Повернення оформлюється актом до вівторка [Продавець-приймальник, День 3]."
            if "процедура повернення" in user_q:
                return NO_ANSWER_MARKER
            return "Вітайте покупця та видайте чек [День 1]."

        def domain_vec(txt: str) -> list[float]:
            if "Космодром" in txt or "Марс" in txt:
                return [0.0, 0.0, 0.0, 1.0]
            return [1.0, 0.0, 0.0, 0.0]

        fake_client = _FakeOpenAIClient(vector_fn=domain_vec, chat_handler=rc_chat_handler)
        res_empty_role = await answer_remind_topic(
            question="Повернення на РЦ",
            role_filter="Комплектувальник-приймальник",
            user_id=5227105573,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(res_empty_role["status"], "ok")
        self.assertTrue(res_empty_role["used_network_fallback"])
        self.assertIn("У матеріалах твоєї посади відповіді не знайдено", res_empty_role["text"])
        self.assertIn("Продавець-приймальник", res_empty_role["text"])

        # 2) Role WITH answer in own materials stops at Stage 1 without mixing network.
        fake_client.chat.completions.calls.clear()
        res_own_role = await answer_remind_topic(
            question="Як обслуговувати на касі?",
            role_filter="Продавець-консультант (каса)",
            user_id=111,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(res_own_role["status"], "ok")
        self.assertFalse(res_own_role["used_network_fallback"])
        self.assertEqual(len(fake_client.chat.completions.calls), 1)
        self.assertNotIn("Продавець-приймальник", res_own_role["text"])

        # 3) Role whose Stage 1 chunk lacks specific answer triggers Stage 2 via NO_ANSWER_MARKER.
        fake_client.chat.completions.calls.clear()
        res_stage2 = await answer_remind_topic(
            question="Яка процедура повернення товару на РЦ?",
            role_filter="Продавець-консультант (каса)",
            user_id=222,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(res_stage2["status"], "ok")
        self.assertTrue(res_stage2["used_network_fallback"])
        self.assertEqual(len(fake_client.chat.completions.calls), 2)
        self.assertIn("Продавець-приймальник", res_stage2["text"])

        # 4) Global mode returns directly without network fallback preamble.
        res_global = await answer_remind_topic(
            question="Повернення на РЦ",
            role_filter=None,
            user_id=738460434,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(res_global["status"], "ok")
        self.assertFalse(res_global["used_network_fallback"])

        # 5) OpenAI failure -> clean lexical fallback without raw JSON.
        failing_client = _FailingOpenAIClient()
        res_fallback = await answer_remind_topic(
            question="Повернення на РЦ",
            role_filter="Комплектувальник-приймальник",
            user_id=5227105573,
            db_path=self.db_path,
            client=failing_client,
        )
        self.assertEqual(res_fallback["status"], "fallback_lexical")
        self.assertIn("актом повернення на РЦ", res_fallback["text"])
        self.assertNotIn("AgACAg", res_fallback["text"])

        # 6) Unrelated question with orthogonal embedding -> not_found without even needing GPT.
        fake_client.chat.completions.calls.clear()
        res_none = await answer_remind_topic(
            question="Космодром на Марсі",
            role_filter="Комплектувальник-приймальник",
            user_id=5227105573,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(res_none["status"], "not_found")
        self.assertEqual(len(fake_client.chat.completions.calls), 0)

        # 7) Short keyword query 'РЦ' in global scope forbids NO_ANSWER_MARKER in prompt,
        # and even an adversarial GPT returning NO_ANSWER_MARKER degrades safely to lexical excerpts (never 'not_found').
        fake_client.chat.completions.calls.clear()
        res_rc_ok = await answer_remind_topic(
            question="РЦ",
            role_filter=None,
            user_id=738460434,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(res_rc_ok["status"], "ok")
        self.assertEqual(len(fake_client.chat.completions.calls), 1)
        rc_sys_prompt = fake_client.chat.completions.calls[0]["messages"][0]["content"]
        self.assertNotIn(NO_ANSWER_MARKER, rc_sys_prompt)

        adversarial_client = _FakeOpenAIClient(
            vector_fn=domain_vec,
            chat_handler=lambda kwargs, idx: NO_ANSWER_MARKER,
        )
        res_rc_adversarial = await answer_remind_topic(
            question="РЦ",
            role_filter=None,
            user_id=738460434,
            db_path=self.db_path,
            client=adversarial_client,
        )
        self.assertEqual(res_rc_adversarial["status"], "fallback_lexical")
        self.assertNotIn(NO_ANSWER_MARKER, res_rc_adversarial["text"])
        self.assertIn("РЦ", res_rc_adversarial["text"])
        self.assertEqual(len(adversarial_client.chat.completions.calls), 1)

    async def test_domain_synonyms_copy_paste_cleanup_and_topic_lists(self):
        async with aiosqlite.connect(self.db_path) as db:
            # 12 distinct RC chunks + 2 distinct Sklad chunks + ТТ + ф/о + non-matching distractor with 'працівники'
            for i in range(1, 13):
                filler = f"Загальний опис операцій зміни #{i} для торгової зали та касової зони. " * 6
                await db.execute(
                    "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                    (f"Роль РЦ {i}", 1, f"Поставки {i}", f"{filler}\n\nПрийом поставки з РЦ #{i}: перевірити накладні РЦ."),
                )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Старший продавець", 2, "Склад", "Склад магазину: підтримувати прохід вільним та маркувати стелажі на складі."),
            )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Приймальник", 2, "Овочі", "Склад ф/о приймає ящики з фруктами та овочами щодня зранку на ТТ."),
            )
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, ?, 'text', ?, ?)",
                ("Касир", 1, "Загальне", "Працівники магазину проходять інструктаж перед першою зміною."),
            )
            await db.commit()

        # Deliberately give weak embedding similarity to 'РЦ' vs noise so bidirectional synonym rules must carry retrieval
        def vec_fn(txt: str) -> list[float]:
            if "Працівники" in txt or "Місяць" in txt:
                return [1.0, 0.0, 0.0]
            if "РЦ" in txt or "Розподільчий центр" in txt:
                return [0.7, 0.7, 0.0]
            return [0.0, 0.0, 1.0]

        def smart_chat(kwargs, call_idx):
            sys_prompt = kwargs["messages"][0]["content"]
            user_prompt = kwargs["messages"][1]["content"]
            if "Місяць" in user_prompt:
                return NO_ANSWER_MARKER
            if "Прийом поставки з РЦ #1" in sys_prompt and "Прийом поставки з РЦ #12" in sys_prompt:
                return "Знайдено всі правила по РЦ та складу [Роль РЦ 1, День 1]."
            return "Знайдено інструкцію [День 2]."

        fake_client = _FakeOpenAIClient(vector_fn=vec_fn, chat_handler=smart_chat)

        # 1) Full name 'Розподільчий центр' must find ALL 12 chunks written as 'РЦ' + enrich GPT prompt + disable NO_ANSWER_MARKER
        search_rc_full = await hybrid_search_chunks(
            query="Розподільчий центр",
            role_filter=None,
            scope="global",
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertTrue(search_rc_full["has_relevant_match"])
        self.assertEqual(search_rc_full["concept_count"], 1)
        joined_rc = "\n".join(r["excerpt"] for r in search_rc_full["results"])
        for i in range(1, 13):
            self.assertIn(f"Прийом поставки з РЦ #{i}", joined_rc)

        fake_client.chat.completions.calls.clear()
        ans_rc_full = await answer_remind_topic(
            question="Розподільчий центр",
            role_filter=None,
            user_id=738460434,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(ans_rc_full["status"], "ok")
        self.assertEqual(len(fake_client.chat.completions.calls), 1)
        sys_p = fake_client.chat.completions.calls[0]["messages"][0]["content"]
        self.assertNotIn(NO_ANSWER_MARKER, sys_p)
        self.assertIn("«РЦ»", sys_p)

        # 2) Copy-paste noisy query 'Розподільчий центр, склад 09:29 //' strips '09:29 //', hits both РЦ and склад, and returns ok
        fake_client.chat.completions.calls.clear()
        ans_combo = await answer_remind_topic(
            question="Розподільчий центр, склад 09:29 //",
            role_filter=None,
            user_id=738460434,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(ans_combo["status"], "ok")
        combo_sys = fake_client.chat.completions.calls[0]["messages"][0]["content"]
        combo_user = fake_client.chat.completions.calls[0]["messages"][1]["content"]
        self.assertNotIn("09:29", combo_user)
        self.assertNotIn("//", combo_user)
        self.assertNotIn(NO_ANSWER_MARKER, combo_sys)
        self.assertIn("Склад магазину", combo_sys)
        self.assertIn("Прийом поставки з РЦ #12", combo_sys)

        # 3) Combined synonymous + extra list ('РЦ, розподільчий центр, склад') deduplicates concepts to 2
        res_dup_list = await hybrid_search_chunks("РЦ, розподільчий центр, склад", role_filter=None, scope="global", db_path=self.db_path, client=fake_client)
        self.assertEqual(res_dup_list["concept_count"], 2)
        self.assertTrue(res_dup_list["is_topic_list"])

        # 4) Bidirectional aliases: 'фрукти та овочі' hits 'Склад ф/о' and 'Торгова точка' hits 'ТТ'
        search_fo = await hybrid_search_chunks("фрукти та овочі", role_filter=None, scope="global", db_path=self.db_path, client=fake_client)
        self.assertTrue(any("Склад ф/о" in r["excerpt"] for r in search_fo["results"]))
        self.assertTrue(any(r["is_exact_match"] for r in search_fo["results"]))

        search_tt = await hybrid_search_chunks("Торгова точка", role_filter=None, scope="global", db_path=self.db_path, client=fake_client)
        self.assertTrue(any("щодня зранку на ТТ" in r["excerpt"] for r in search_tt["results"]))
        self.assertTrue(any(r["is_exact_match"] for r in search_tt["results"]))

        # 4) Non-existent topic even when an unspecific word ('працівники') matches still returns 'not_found'
        fake_client.chat.completions.calls.clear()
        ans_moon = await answer_remind_topic(
            question="Коли працівники Булки летять на Місяць?",
            role_filter=None,
            user_id=738460434,
            db_path=self.db_path,
            client=fake_client,
        )
        self.assertEqual(ans_moon["status"], "not_found")


class TestRemindHandlersAndDynamicRoles(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_handlers.db")
        await _create_test_db(self.db_path)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO positions (name, territorial_type) VALUES (?, 'ТЗ')", ("Керівник",))
            await db.execute("INSERT INTO positions (name, territorial_type) VALUES (?, 'РЦ')", ("Комплектувальник-приймальник",))
            await db.execute(
                "INSERT INTO materials (role, day, content_type, title, content) VALUES (?, 1, 'text', 'Д1', 'Тест інструкції КТТ')",
                ("Керівник ТТ",),
            )
            await db.commit()

    async def asyncTearDown(self):
        self.tmp_dir.cleanup()

    async def test_get_searchable_roles_unions_positions_and_materials(self):
        admin_roles = await get_searchable_roles(exclude_manager_roles=False, db_path=self.db_path)
        self.assertIn("Керівник", admin_roles)
        self.assertIn("Комплектувальник-приймальник", admin_roles)
        self.assertIn("Керівник ТТ", admin_roles)

        mgr_roles = await get_searchable_roles(exclude_manager_roles=True, db_path=self.db_path)
        self.assertNotIn("Керівник", mgr_roles)
        self.assertIn("Комплектувальник-приймальник", mgr_roles)

    async def test_dev_test_all_roles_and_zero_material_role_flow(self):
        from bot.handlers import (
            process_keyword_search,
            remind_role_select_callback,
            remind_topic_global_callback,
        )
        from bot.menus.manager import manager_process_remind_role, manager_remind_menu

        edited_calls: list[dict] = []

        class _DummyMessage:
            def __init__(self, text="", user_id=1001226587):
                self.text = text
                self.photo = None
                self.from_user = SimpleNamespace(id=user_id)
                self.replies: list[dict] = []

            async def answer(self, text, **kwargs):
                msg = _DummyMessage(text=text)
                self.replies.append({"text": text, **kwargs})
                return msg

            async def edit_text(self, text, **kwargs):
                edited_calls.append({"text": text, **kwargs})

            async def delete(self):
                return True

        cb_msg = _DummyMessage()
        callback = SimpleNamespace(
            data="remind_topic_global",
            from_user=SimpleNamespace(id=1001226587),
            message=cb_msg,
            answer=AsyncMock(),
        )
        state = _FakeFSMContext()
        roles_fixture = ["Керівник ТТ", "Комплектувальник-приймальник"]

        with (
            patch("bot.handlers.is_hr_user", AsyncMock(return_value=True)),
            patch("bot.handlers.is_developer_user", AsyncMock(return_value=True)),
            patch("bot.handlers.is_observer_user", AsyncMock(return_value=False)),
            patch("bot.handlers.is_manager_user", AsyncMock(return_value=False)),
            patch("bot.handlers.get_searchable_roles", AsyncMock(return_value=roles_fixture)),
        ):
            await remind_topic_global_callback(callback, state)
            self.assertEqual(state.data.get("remind_roles_list"), roles_fixture)
            kb = edited_calls[-1]["reply_markup"]
            btn_texts = [b.text for row in kb.inline_keyboard for b in row]
            btn_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
            self.assertIn("👤 Керівник ТТ", btn_texts)
            self.assertIn("🌐 Всі посади", btn_texts)
            self.assertIn("remind_role_select:ALL", btn_cbs)

            # Select dynamic role 'Керівник ТТ' by index
            select_cb = SimpleNamespace(
                data="remind_role_select:0",
                from_user=SimpleNamespace(id=1001226587),
                message=cb_msg,
                answer=AsyncMock(),
            )
            await remind_role_select_callback(select_cb, state)
            self.assertEqual(state.data.get("role"), "Керівник ТТ")
            self.assertEqual(state.data.get("mode"), "dev_test")

            # Select ALL -> role=None, mode="dev_test"
            select_all_cb = SimpleNamespace(
                data="remind_role_select:ALL",
                from_user=SimpleNamespace(id=1001226587),
                message=cb_msg,
                answer=AsyncMock(),
            )
            await remind_role_select_callback(select_all_cb, state)
            self.assertIsNone(state.data.get("role"))
            self.assertEqual(state.data.get("mode"), "dev_test")

        # Now process_keyword_search with mode="dev_test" & role=None MUST NOT fall back to 'Developer'
        user_msg = _DummyMessage(text="РЦ", user_id=1001226587)
        captured_calls: list[dict] = []

        async def _fake_answer_remind_topic(question, role_filter=None, user_id=None, **kwargs):
            captured_calls.append({"question": question, "role_filter": role_filter, "user_id": user_id})
            return {"status": "ok", "text": "Усі правила про РЦ...", "used_network_fallback": False, "used_gpt": True, "matches": []}

        with (
            patch("bot.handlers.is_hr_user", AsyncMock(return_value=False)),
            patch("bot.handlers.is_developer_user", AsyncMock(return_value=True)),
            patch("bot.handlers.is_observer_user", AsyncMock(return_value=False)),
            patch("bot.handlers.is_manager_user", AsyncMock(return_value=False)),
            patch("bot.handlers.get_user_details", AsyncMock(return_value={"role": "Developer"})),
            patch("bot.handlers.answer_remind_topic", side_effect=_fake_answer_remind_topic),
        ):
            await process_keyword_search(user_msg, state)

        self.assertEqual(len(captured_calls), 1)
        self.assertIsNone(captured_calls[0]["role_filter"])
        self.assertTrue(any("BULKA радник" in r["text"] for r in user_msg.replies))

        # Test long answer splitting (>4000 chars) sends multiple parts instead of truncating.
        long_state = _FakeFSMContext({"mode": "self", "role": "Комплектувальник-приймальник"})
        long_body = "\n\n".join([f"<b>Пункт {i}:</b> Докладна інструкція про РЦ та приймання товару." * 3 for i in range(1, 35)])
        long_msg = _DummyMessage(text="РЦ", user_id=5227105573)
        with (
            patch("bot.handlers.is_privileged_user", AsyncMock(return_value=False)),
            patch("bot.handlers.get_user_details", AsyncMock(return_value={"role": "Комплектувальник-приймальник", "manager_id": 99})),
            patch("bot.handlers._has_completed_course", AsyncMock(return_value=True)),
            patch(
                "bot.handlers.answer_remind_topic",
                AsyncMock(return_value={"status": "ok", "text": long_body, "used_network_fallback": True, "used_gpt": True, "matches": []}),
            ),
        ):
            await process_keyword_search(long_msg, long_state)

        answer_replies = [r for r in long_msg.replies if "аналізує" not in r["text"]]
        self.assertGreater(len(answer_replies), 1)
        self.assertNotIn("відповідь обрізано", answer_replies[-1]["text"])

        # Manager remind menu includes '🌐 Всі посади' and mgr_remind_role:ALL
        mgr_state = _FakeFSMContext()
        mgr_edited: list[dict] = []
        with (
            patch("bot.menus.manager._ensure_manager", AsyncMock(return_value=True)),
            patch("bot.menus.manager.get_searchable_roles", AsyncMock(return_value=["Продавець"])),
            patch("bot.menus.manager._edit_menu_message", side_effect=lambda m, t, kb, **kw: mgr_edited.append({"text": t, "kb": kb})),
        ):
            mgr_cb = SimpleNamespace(
                data="mgr_remind_menu",
                from_user=SimpleNamespace(id=99),
                message=cb_msg,
                answer=AsyncMock(),
            )
            await manager_remind_menu(mgr_cb, mgr_state)
            mgr_cbs = [b.callback_data for row in mgr_edited[-1]["kb"].inline_keyboard for b in row]
            self.assertIn("mgr_remind_role:ALL", mgr_cbs)

            mgr_select_all = SimpleNamespace(
                data="mgr_remind_role:ALL",
                from_user=SimpleNamespace(id=99),
                message=cb_msg,
                answer=AsyncMock(),
            )
            await manager_process_remind_role(mgr_select_all, mgr_state)
            self.assertIsNone(mgr_state.data.get("role"))
            self.assertEqual(mgr_state.data.get("mode"), "manager_global")


if __name__ == "__main__":
    unittest.main()
