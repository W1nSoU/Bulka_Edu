# Implementation Plan: Додавання динамічної камери (Ken Burns) у CapCut

**Дата:** 2026-11-11  
**Специфікація:** [docs/superpowers/specs/2026-11-11-capcut-camera-motion-dynamics-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-11-capcut-camera-motion-dynamics-design.md)  
**Проєкт CapCut:** `1111`  
**Серія:** 04 (`04_Friction_Fire`)

---

## Завдання

### Етап 1: Підготовка та резервна копія
- [ ] Перевірити, що CapCut закритий.
- [ ] Створити бекап проєкту `1111` в `/tmp/capcut_backup_1111_pre_motion`.

### Етап 2: Розробка скрипта автоматизації динаміки камери
- [ ] Зчитати типи форматів (Hybrid, Diagram, 2D Comic, Diptych/Triptych 2D) для всіх 200 кадрів з файлу `02_storyboard_shots.md`.
- [ ] Створити скрипт генерації `common_keyframes` відповідно до правил:
  - **Hybrid (Zoom-In 60%):** `UNIFORM_SCALE` від `1.00` до `1.07`.
  - **Hybrid (Pan 40%):** `UNIFORM_SCALE` = `1.05`, `KFTypePositionX` від `-0.025` до `+0.025` (чергуючи напрямок ліво-право).
  - **Diagram:** `UNIFORM_SCALE` від `1.00` до `1.03` (або статика, якщо тривалість < 3.2 с).
  - **2D Comic:** `UNIFORM_SCALE` від `1.00` до `1.09`.
  - **Diptych/Triptych 2D:** `UNIFORM_SCALE` = `1.04`, `KFTypePositionX` від `-0.020` до `+0.020` (панорамування зліва направо).

### Етап 3: Застосування до файлів проєкту
- [ ] Оновити об'єкти `segments` у `draft_info.json` у корені проєкту.
- [ ] Оновити `draft_info.json` у папці `Timelines/*/`.
- [ ] Оновити супутні копії `.bak` та `template-2.tmp`.

### Етап 4: Валідація та перевірка цілісності
- [ ] Перевірити валідність JSON структури.
- [ ] Переконатися, що всі 200 сегментів отримали ключові кадри без пошкодження часових меж (30 fps).
- [ ] Зафіксувати результати та повідомити користувача.
