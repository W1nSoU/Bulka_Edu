# План реалізації: Підвищення шансу спавну модових структур та печер (2.5×–3× Boost)

Цей план описує покроковий процес налаштування конфігурацій та створення датапаку в KubeJS для збалансованого збільшення щільності появи всіх модових структур і біомів печер.

---

### Крок 1. Конфігурація Alex's Caves (`config/`)
- [ ] Оновити `config/alexscaves-general.toml`:
  - Зменшити `cave_biome_mean_separation` з `900` до `380`.
- [ ] Оновити `config/alexscaves_biome_generation/*.json`:
  - `abyssal_chasm.json`: встановити `distance_from_spawn = 150`.
  - `primordial_caves.json`: встановити `distance_from_spawn = 150`.
  - `magnetic_caves.json`: встановити `distance_from_spawn = 150`.
  - `toxic_caves.json`: встановити `distance_from_spawn = 200`.
  - `forlorn_hollows.json`: встановити `distance_from_spawn = 200`.

---

### Крок 2. Конфігурація Ice and Fire (`config/iceandfire-common.toml`)
- [ ] Зменшити буфер спавну `"Dangerous World Gen Dist From Spawn"` з `800` до `300`.
- [ ] Збільшити частоту появи лігв та гнізд:
  - `"Generate Dragon Roost Chance"`: з `360` до `140`.
  - `"Generate Dragon Cave Chance"`: з `30` до `18`.
- [ ] Підвищити частоту інших міфічних структур:
  - `"Spawn Cyclops Cave Chance"`: з `100` до `40`.
  - `"Spawn Sirens Chance"`: з `400` до `160`.
  - `"Hydra Caves Gen Chance"`: з `60` до `25`.
  - `"Spawn Wandering Cyclops Chance"`: з `100` до `40`.

---

### Крок 3. Набори структур Iron's Spells and Spellbooks (`kubejs/data/irons_spellbooks/worldgen/structure_set/`)
- [ ] Витягнути та створити перевизначення наборів структур зі зменшенням `spacing` та `separation` у ~2.5 рази:
  - `ancient_battleground.json`: `spacing = 15`, `separation = 6`
  - `catacombs.json`: `spacing = 28`, `separation = 14`
  - `evoker_fort.json`: `spacing = 32`, `separation = 16`
  - `impaled_icebreaker.json`: `spacing = 30`, `separation = 15`
  - `mangrove_hut.json`: `spacing = 12`, `separation = 6`
  - `mountain_tower.json`: `spacing = 18`, `separation = 10`
  - `pyromancer_tower.json`: `spacing = 32`, `separation = 16`

---

### Крок 4. Набори структур L_Ender's Cataclysm (`kubejs/data/cataclysm/worldgen/structure_set/`)
- [ ] Створити перевизначення наборів структур Cataclysm:
  - `burning_arena.json`: `spacing = 35`, `separation = 18`
  - `soul_black_smith.json`: `spacing = 35`, `separation = 18`
  - `cursed_pyramid.json`: `spacing = 35`, `separation = 18`
  - `sunken_city.json`: `spacing = 35`, `separation = 18`
  - `ancient_factory.json`: `spacing = 35`, `separation = 18`
  - `frosted_prison.json`: `spacing = 35`, `separation = 18`
  - `ruined_citadel.json`: `spacing = 35`, `separation = 18`

---

### Крок 5. Набори структур Dungeons and Taverns (`kubejs/data/dungeons_and_taverns/worldgen/structure_set/`)
- [ ] Витягнути всі наявні набори структур із jar-файлу `dungeons-and-taverns`.
- [ ] Зменшити `spacing` та `separation` кожного набору у ~2.3×–2.5×, зберігаючи інваріант `separation < spacing`.

---

### Крок 6. Набори структур YUNG's Better Dungeons, Mowzie's Mobs, Dungeon Now Loading, Eidolon, Mine Cells
- [ ] `betterdungeons`: змасштабувати набори малих підземель (скелети, зомбі, павуки, незер).
- [ ] `mowziesmobs`: `frostmaw_spawns`, `monasteries`, `umvuthana_groves`, `wrought_nautilus` (масштаб 2.5×).
- [ ] `dungeonnowloading`: `labyrinth`, `temple_of_duality` (масштаб 2.5×).
- [ ] `eidolon`: `catacomb`, `lab`, `stray_tower` (масштаб 2.5×).
- [ ] `minecells`: `overworld_portal` (масштаб 2.5×).

---

### Крок 7. Валідація та перевірка
- [ ] Запустити скрипт валідації синтаксису всіх згенерованих JSON та TOML файлів.
- [ ] Перевірити сувору умову: `separation < spacing` для кожного набору.
- [ ] Перевірити, що всі файли розміщені за валідними шляхами простору імен KubeJS.
