# Design Spec: Modded Structures & Cave Biomes Spawn Rate Boost

## 1. Overview & Goals
Players on the world save `With Benik65` (Minecraft 1.20.1 Forge, 311 mods) experienced overly sparse world generation that felt too close to vanilla Minecraft. Modded structures and cave biomes (Alex's Caves, Iron's Spells and Spellbooks, L_Ender's Cataclysm, Dungeons and Taverns, YUNG's Better Dungeons, Ice and Fire, Mowzie's Mobs, Dungeon Now Loading, Eidolon, Mine Cells) were generating with huge separations (often 800–1400+ blocks apart) or locked behind distance-from-spawn buffers (400–800 blocks).

The goal is to increase the spawn rate of all modded structures and cave biomes by **2.5× to 3× balanced boost** without causing excessive structure overlaps or severe performance/TPS degradation.

---

## 2. Scope & Target Mods

### 2.1 Direct Configuration Files (`config/`)
1. **Alex's Caves** (`alexscaves-general.toml` & `config/alexscaves_biome_generation/*.json`):
   - Decrease `cave_biome_mean_separation` from `900` to `380` blocks (~2.4× closer cave biomes).
   - Decrease `distance_from_spawn` across all 5 cave biomes:
     - `abyssal_chasm.json`: 400 ➔ 150 blocks
     - `primordial_caves.json`: 450 ➔ 150 blocks
     - `magnetic_caves.json`: 400 ➔ 150 blocks
     - `toxic_caves.json`: 650 ➔ 200 blocks
     - `forlorn_hollows.json`: 650 ➔ 200 blocks

2. **Ice and Fire** (`iceandfire-common.toml`):
   - `"Dangerous World Gen Dist From Spawn"`: 800 ➔ 300 blocks.
   - `"Generate Dragon Roost Chance"`: 360 ➔ 140 (~2.6× more frequent surface roosts).
   - `"Generate Dragon Cave Chance"`: 30 ➔ 18 (~1.7× more frequent underground dens / Stage 4-5 mothers).
   - `"Spawn Cyclops Cave Chance"`: 100 ➔ 40.
   - `"Spawn Sirens Chance"`: 400 ➔ 160.
   - `"Hydra Caves Gen Chance"`: 60 ➔ 25.
   - `"Spawn Wandering Cyclops Chance"`: 100 ➔ 40.

---

### 2.2 KubeJS Worldgen Datapack (`kubejs/data/<namespace>/worldgen/structure_set/*.json`)
In Minecraft 1.20.1 Forge, structure spawn distribution is driven by vanilla `worldgen/structure_set` JSON files (`spacing` and `separation` in chunks). We place overrides into `kubejs/data/`:

1. **Iron's Spells and Spellbooks** (`irons_spellbooks`):
   - `ancient_battleground.json`: spacing 35 ➔ 15, separation 12 ➔ 6
   - `catacombs.json`: spacing 72 ➔ 28, separation 48 ➔ 14
   - `evoker_fort.json`: spacing 85 ➔ 32, separation 50 ➔ 16
   - `impaled_icebreaker.json`: spacing 75 ➔ 30, separation 50 ➔ 15
   - `mangrove_hut.json`: spacing 25 ➔ 12, separation 18 ➔ 6
   - `mountain_tower.json`: spacing 45 ➔ 18, separation 33 ➔ 10
   - `pyromancer_tower.json`: spacing 85 ➔ 32, separation 50 ➔ 16

2. **L_Ender's Cataclysm** (`cataclysm`):
   - `burning_arena.json`: spacing 80 ➔ 35, separation 50 ➔ 18
   - `soul_black_smith.json`: spacing 80 ➔ 35, separation 50 ➔ 18
   - `cursed_pyramid.json`: spacing 80 ➔ 35, separation 50 ➔ 18
   - `sunken_city.json`: spacing 80 ➔ 35, separation 50 ➔ 18
   - `ancient_factory.json`: spacing 80 ➔ 35, separation 50 ➔ 18
   - `frosted_prison.json`: spacing 80 ➔ 35, separation 50 ➔ 18
   - `ruined_citadel.json`: spacing 80 ➔ 35, separation 50 ➔ 18

3. **Dungeons and Taverns** (`dungeons_and_taverns` / `dungeonsplus`):
   - All 24 structure sets (bunkers, taverns, outposts, underground towers, etc.):
   - Scale spacing by ~2.3×–2.5× down (e.g. 45–65 ➔ 18–26, keeping separation < spacing).

4. **YUNG's Better Structures** (`betterdungeons`, `betterjungletemples`, `betterwitchhuts`, `bettermineshafts`):
   - `skeleton_dungeons`, `small_dungeons`, `small_nether_dungeons`, `spider_dungeons`, `zombie_dungeons`: scale spacing by ~2.2× down.
   - Jungle temples, witch huts, mineshafts: scale spacing down proportionally.

5. **Mowzie's Mobs, Dungeon Now Loading, Eidolon, Mine Cells**:
   - `mowziesmobs`: `frostmaw_spawns`, `monasteries`, `umvuthana_groves`, `wrought_nautilus` (scaled by 2.5×).
   - `dungeonnowloading`: `labyrinth`, `temple_of_duality` (scaled by 2.5×).
   - `eidolon`: `catacomb`, `lab`, `stray_tower` (scaled by 2.5×).
   - `minecells`: `overworld_portal` (scaled by 2.5×).

---

## 3. Data Flow & Execution Mechanics
1. On world load or chunk generation, Minecraft combines `worldgen/structure_set` from datapacks (`kubejs/data/`).
2. The `RandomSpreadStructurePlacement` reads the new `spacing` and `separation` values.
3. Newly generated chunks calculate structure candidates with shorter intervals, generating structures 2.5× more frequently.
4. Existing chunks (where players already built their base) remain unchanged and intact.
5. In newly explored chunks, structures will generate with the increased density.

---

## 4. Verification & Testing
1. Validate all created JSON files for valid JSON syntax.
2. Ensure every structure set satisfies the invariant: `separation < spacing`.
3. Check `alexscaves-general.toml` and `iceandfire-common.toml` formatting.
4. Launch/test script to verify KubeJS data loading without parse errors.
