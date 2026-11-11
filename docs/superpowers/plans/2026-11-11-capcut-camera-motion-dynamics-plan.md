# Implementation Plan: Додавання динамічної камери (Ken Burns) у CapCut

**Дата:** 2026-11-11  
**Специфікація:** [docs/superpowers/specs/2026-11-11-capcut-camera-motion-dynamics-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-11-capcut-camera-motion-dynamics-design.md)  
**Проєкт CapCut:** `1111`  
**Серія:** 04 (`04_Friction_Fire`)

---

## Завдання

### Етап 1: Підготовка та резервна копія
- [x] Перевірити, що CapCut закритий.
- [x] Створити бекап проєкту `1111` в `/tmp/capcut_backup_1111_pre_motion`.

### Етап 2: Розробка скрипта автоматизації динаміки камери
- [x] Зчитати типи форматів (Hybrid, Diagram, 2D Comic, Diptych/Triptych 2D) для всіх 200 кадрів з файлу `02_storyboard_shots.md`.
- [x] Створити скрипт генерації `common_keyframes` відповідно до правил:
  - **Hybrid (Zoom-In 60%):** `UNIFORM_SCALE` від `1.00` до `1.07`.
  - **Hybrid (Pan 40%):** `UNIFORM_SCALE` = `1.05`, `KFTypePositionX` від `-0.025` до `+0.025` (чергуючи напрямок ліво-право).
  - **Diagram:** `UNIFORM_SCALE` від `1.00` до `1.035` (або статика, якщо тривалість < 3.2 с).
  - **2D Comic:** `UNIFORM_SCALE` від `1.00` до `1.09`.
  - **Diptych/Triptych 2D:** `UNIFORM_SCALE` = `1.04`, `KFTypePositionX` від `-0.020` до `+0.020` (панорамування зліва направо).

### Етап 3: Застосування до файлів проєкту
- [x] Оновити об'єкти `segments` у `draft_info.json` у корені проєкту.
- [x] Оновити `draft_info.json` у папці `Timelines/*/`.
- [x] Оновити супутні копії `.bak` та `template-2.tmp`.

### Етап 4: Валідація та перевірка цілісності
- [x] Перевірити валідність JSON структури.
- [x] Переконатися, що всі 200 сегментів отримали ключові кадри без пошкодження часових меж (30 fps).
- [x] Зафіксувати результати та повідомити користувача.
