# План реалізації: Виняток для закріплених за Шилоносовою В.О. у списку без керівника

**Специфікація:** [2026-11-12-shylonosova-store-manager-exemption-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-12-shylonosova-store-manager-exemption-design.md)  
**Дата:** 2026-11-12  

---

## Крок 1: Оновлення логіки у `database/managers.py`
- У функції `is_user_without_store_manager(user: dict) -> bool`:
  - Отримати дані закріпленого керівника `mgr = await get_manager_by_uid(manager_id)`.
  - Якщо `mgr and mgr.get("status") != "fired"`:
    - Перевірити `"шилоносова" in (mgr.get("full_name") or "").lower()`.
    - Якщо True -> повернути `False`.

## Крок 2: Додавання модульних тестів
- Створити або оновити тест у `tests/test_shylonosova_exemption.py`:
  - Перевірити, що стажер Шилоносової повертає `is_user_without_store_manager == False`.
  - Перевірити, що стажер іншого територіала повертає `True`.
  - Перевірити, що стажер без керівника повертає `True`.

## Крок 3: Запуск тестів та верифікація
- Запустити тест через `uv run --with-requirements requirements.txt python3 -m unittest ...`
