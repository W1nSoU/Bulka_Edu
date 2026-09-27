# Design Spec: Disable Mine Cells Cursed Sword Curse & Instant Death

**Date:** 2026-09-27  
**Status:** Approved  
**Topic:** Disable `minecells:cursed` effect and instant death for players using `minecells:cursed_sword`

---

## 1. Context & Background
In the mod **Mine Cells** (v1.8.2 on Forge 1.20.1), wielding the `minecells:cursed_sword` periodically applies the `minecells:cursed` status effect to the player. When this effect is active:
- Any incoming damage (including minor damage such as bleed, poison, or fall damage) triggers `LivingEntityMixin.minecells$injectDamage`, which plays a curse sound and deals **2048.0 lethal damage** of type `minecells.cursed` ("предался проклятию").
- The player wishes to use the Cursed Sword as a potent weapon without receiving the curse effect or suffering instant death upon taking damage.

---

## 2. Requirements & Goals
1. **Prevent Curse Application:** Prevent the `minecells:cursed` effect from being applied to the player when holding or swinging `minecells:cursed_sword`.
2. **Prevent Instant Death:** In the event that the curse effect is active or applied via an edge case, completely negate/cancel any lethal damage coming from the `minecells.cursed` damage source.
3. **Non-invasive Implementation:** Accomplish this via KubeJS scripts without modifying or recompiling the `minecells-1.8.2.jar` mod binary.
4. **Safety & Stability:** Normal damage sources (fall damage, enemy attacks, environmental hazards) must continue to function normally.

---

## 3. Architecture & Implementation Plan

### 3.1 Startup Script (`kubejs/startup_scripts/main.js`)
- **Event:** Forge event `net.minecraftforge.event.entity.living.MobEffectEvent$Applicable`.
- **Target:** Check if the entity is a player and the effect matches `effect.minecells.cursed` or `minecells:cursed`.
- **Action:** Set event result to `Event$Result.DENY` using `Java.loadClass('net.minecraftforge.eventbus.api.Event$Result')`.
- **Purpose:** Blocks the effect at the Forge engine level before it can be added to the player entity.

### 3.2 Server Script (`kubejs/server_scripts/main.js`)
- **Component 1 (Active Effect Stripping):**
  - **Event:** `PlayerEvents.tick`
  - **Action:** Check `player.hasEffect('minecells:cursed')`. If present, invoke `player.removeEffect('minecells:cursed')`.
  - **Purpose:** Automatically removes existing or bypassed curse instances and clears `MineCellsEffectFlags.CURSED`.
- **Component 2 (Damage Negation):**
  - **Event:** `EntityEvents.hurt`
  - **Action:** Check if `event.entity.isPlayer()` and `event.source.getMsgId() === 'minecells.cursed'`. If matched, invoke `event.cancel()`.
  - **Purpose:** Safeguard against instant 2048 death if curse damage is dispatched.

---

## 4. Verification & Testing Protocol
1. **Script Syntax & Reload:**
   - Execute `/reload` or `/kubejs reload server_scripts` in-game to verify syntax in `kubejs/server_scripts/main.js`.
   - Inspect `logs/kubejs/server.log` to ensure no errors were encountered during compilation/execution.
2. **Behavioral In-Game Test:**
   - Equip `minecells:cursed_sword` in the main hand.
   - Verify that the player does not have the curse status effect icon.
   - Take damage from a non-lethal source (e.g., fall damage or cactus).
   - Verify that the player survives and takes only normal damage, without dying to "предался проклятию".
3. **Startup Event Verification:**
   - On subsequent full client restarts, verify `logs/kubejs/startup.log` shows clean initialization of the Forge event listener.
