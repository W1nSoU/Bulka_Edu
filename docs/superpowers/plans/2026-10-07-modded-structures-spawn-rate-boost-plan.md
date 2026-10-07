# План реалізації: Підвищення шансу спавну модових структур та печер (2.5×–3× Boost)

Цей план описує покроковий процес налаштування конфігурацій та створення датапаку в KubeJS для збалансованого збільшення щільності появи всіх модових структур і біомів печер.

---

### Крок 1. Конфігурація Alex's Caves (`config/`)
- [x] Оновити `config/alexscaves-general.toml`:
  - Зменшити `cave_biome_mean_separation` з `900` до `380`.
- [x] Оновити `config/alexscaves_biome_generation/*.json`:
  - `abyssal_chasm.json`: встановити `distance_from_spawn = 150`.
  - `primordial_caves.json`: встановити `distance_from_spawn = 150`.
  - `magnetic_caves.json`: встановити `distance_from_spawn = 150`.
  - `toxic_caves.json`: встановити `distance_from_spawn = 200`.
  - `forlorn_hollows.json`: встановити `distance_from_spawn = 200`.

---

### Крок 2. Конфігурація Ice and Fire (`config/iceandfire-common.toml`)
- [x] Зменшити буфер спавну `"Dangerous World Gen Dist From Spawn"` з `800` до `300`.
- [x] Збільшити частоту появи лігв та гнізд:
  - `"Generate Dragon Roost Chance"`: з `360` до `140`.
  - `"Generate Dragon Cave Chance"`: з `30` до `18`.
- [x] Підвищити частоту інших міфічних структур:
  - `"Spawn Cyclops Cave Chance"`: з `100` до `40`.
  - `"Spawn Sirens Chance"`: з `400` до `160`.
  - `"Hydra Caves Gen Chance"`: з `60` до `25`.
  - `"Spawn Wandering Cyclops Chance"`: з `100` до `40`.

---

### Крок 3. Набори структур Iron's Spells and Spellbooks (`kubejs/data/irons_spellbooks/worldgen/structure_set/`)
- [x] Створити перевизначення наборів структур зі зменшенням `spacing` та `separation` у ~2.5 рази:
  - `ancient_battleground.json`: `spacing = 15`, `separation = 5`
  - `catacombs.json`: `spacing = 31`, `separation = 19`
  - `evoker_fort.json`: `spacing = 37`, `separation = 20`
  - `impaled_icebreaker.json`: `spacing = 33`, `separation = 20`
  - `mangrove_hut.json`: `spacing = 11`, `separation = 7`
  - `mountain_tower.json`: `spacing = 20`, `separation = 13`
  - `pyromancer_tower.json`: `spacing = 37`, `separation = 20`

---

### Крок 4. Набори структур L_Ender's Cataclysm (`kubejs/data/cataclysm/worldgen/structure_set/`)
- [x] Створити перевизначення наборів структур Cataclysm:
  - `burning_arena.json`: `spacing = 35`, `separation = 20`
  - `soul_black_smith.json`: `spacing = 26`, `separation = 20`
  - `cursed_pyramid.json`: `spacing = 35`, `separation = 20`
  - `sunken_city.json`: `spacing = 43`, `separation = 28`
  - `ancient_factory.json`: `spacing = 49`, `separation = 28`
  - `frosted_prison.json`: `spacing = 35`, `separation = 20`
  - `ruined_citadel.json`: `spacing = 22`, `separation = 10`
  - `acropolis.json`: `spacing = 35`, `separation = 20`

---

### Крок 5. Набори структур Dungeons and Taverns (`kubejs/data/nova_structures/` та `data/minecraft/`)
- [x] Витягнути та переналаштувати всі набори структур `dungeons-and-taverns` (таверни, бункери, аванпости, катакомби тощо).
- [x] Зменшити `spacing` та `separation` кожного набору у ~2.3×–2.5× зі збереженням умови `separation < spacing`.

---

### Крок 6. Набори структур YUNG's Better Dungeons, Mowzie's Mobs, Dungeon Now Loading, Eidolon, Mine Cells, Alex's Caves та ін.
- [x] `betterdungeons`: змасштабовано набори малих підземель (скелети, зомбі, павуки, незер).
- [x] `betterjungletemples`, `betterwitchhuts`, `bettermineshafts`.
- [x] `mowziesmobs`: `frostmaw_spawns`, `monasteries`, `umvuthana_groves`, `wrought_chambers` (масштаб 2.5×).
- [x] `dungeonnowloading`: `labyrinth`, `temple_of_duality` (масштаб 2.5×).
- [x] `eidolon`: `catacomb`, `lab`, `stray_tower` (масштаб 2.5×).
- [x] `minecells`: `overworld_portal` (масштаб 2.5×).
- [x] `alexscaves`: структури всередині печер (вулкани, дино-гнізда, містечка пряників, вежі відьом).
- [x] Інші моди (`ribbits`, `autumnity`, `environmental`, `atmospheric`, `bossesrise`, `bakery`, `brewery`, `netherexp`).

---

### Крок 7. Валідація та перевірка
- [x] Запустити скрипт валідації синтаксису всіх згенерованих JSON та TOML файлів.
- [x] Перевірити сувору умову: `separation < spacing` для кожного набору (89/89 файлів пройшли успішно).
- [x] Перевірити, що всі файли розміщені за валідними шляхами простору імен KubeJS.
