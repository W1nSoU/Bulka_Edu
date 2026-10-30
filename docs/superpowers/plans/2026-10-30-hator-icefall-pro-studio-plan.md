# Implementation Plan: HATOR Icefall PRO Studio (macOS Native App)

- **Date:** 2026-10-30
- **Spec:** [`docs/superpowers/specs/2026-10-30-hator-icefall-pro-studio-design.md`](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-10-30-hator-icefall-pro-studio-design.md)
- **Target Directory:** `/Users/daniildusinskij/All/Dev/hator-icefall-studio`
- **Target Stack:** Electron + Tailwind CSS + Native macOS Swift/IOKit CLI Bridge + WebHID fallback
- **Target Device:** HATOR Icefall PRO G375 (`Icefall 75P -1`, Vendor ID: `0x379A` / `14234`, Product ID: `0x0922` / `2338`, Transport: Bluetooth Low Energy & USB)

---

## 1. Confirmed Hardware Protocol & Reverse Engineering Synthesis

### 1.1 Direct Transport via macOS IOKit
Through live device testing on macOS:
- Bluetooth Low Energy device `Icefall 75P -1` (`0x379A:0x0922`) opens directly with `IOHIDDeviceOpen` without elevated root privileges.
- Vendor usage page `65365` (`0xFF55`), Report ID `0x06` accepts 63-byte output reports (`IOHIDDeviceSetReport(dev, kIOHIDReportTypeOutput, 0x06, payload, 63)`) returning `kIOReturnSuccess`.
- Wired USB interface (Interface 1, Subdevice 7) accepts 8-byte feature reports (`Report ID 0x07` or `0x06`).

### 1.2 Protocol Commands
1. **Dynamic Lighting Effect Command (`0xFA`):**
   - Payload `[0xFA, mode, brightness, speed, direction, color_preset, profile, ...]` (padded to 63 bytes).
   - Modes 1-9: Ambilight, Comet, Curtain, Static, Breathing, Spectroscopy, Wave, Reactive, Custom.
2. **True 16.8M RGB Per-Key Matrix Streaming (`0x1A`):**
   - Transmits sequential chunks:
     - Chunk 0: offset `0x0000`, 56 bytes RGB payload.
     - Chunk 1: offset `0x0038`, 56 bytes RGB payload.
     - Chunk 2: offset `0x0070`, 56 bytes RGB payload.
     - Chunk 3: offset `0x00A8`, 56 bytes RGB payload.
     - Chunk 4: offset `0x00E0`, 56 bytes RGB payload.
     - Chunk 5: offset `0x0118`, 56 bytes RGB payload.
     - Chunk 6: offset `0x0150`, 48 bytes RGB payload.
   - Total 384 bytes covering all 82 keys in the ANSI 75% layout.
3. **Commit to Onboard Flash (`0xFB`):**
   - `[0xFB, profile_id, 0x01, 0x00, ...]`.

---

## 2. Execution Phases & Task Breakdown

### Phase 1: Native macOS HID Bridge CLI (`hator-bridge`)
Build a high-performance, lightweight Swift CLI helper that handles low-level `IOKit.hid` communication with the keyboard over Bluetooth and USB.
- **Task 1.1:** Write `bridge/hator_bridge.swift` implementing:
  - Device discovery and status checking (`hator_bridge status`).
  - Lighting effect dispatcher (`hator_bridge set-mode <mode> <brightness> <speed> <direction> <color>`).
  - True RGB color dispatcher (`hator_bridge set-rgb <hex_or_rgb_list>`).
  - Flash commit dispatcher (`hator_bridge commit <profile>`).
- **Task 1.2:** Compile `hator_bridge` to native Apple Silicon / Intel universal binary.
- **Task 1.3:** Unit test `hator_bridge` directly against the connected `Icefall 75P -1` keyboard.

### Phase 2: Project Scaffolding & Desktop Shell
Create the standalone macOS Electron desktop application `/Users/daniildusinskij/All/Dev/hator-icefall-studio`.
- **Task 2.1:** Create `package.json` with Electron, IPC scripts, and assets.
- **Task 2.2:** Configure `main.js` with frameless macOS window, vibrancy / dark obsidian styling, traffic light integration, and child process bridge spawning.
- **Task 2.3:** Implement secure IPC in `preload.js` exposing keyboard controls to the renderer.

### Phase 3: Modern Desktop UI Implementation
Implement the UI designed in Google Stitch (`hator_icefall_studio.html`).
- **Task 3.1:** Assemble `index.html` with:
  - Header with traffic lights, device badge (`HATOR Icefall PRO G375 [Підʼєднано]`), and profiles (G1, G2, G3).
  - Left navigation sidebar: Основне підсвічування, Запис макросів, OLED Екран, Налаштування.
  - Telemetry footer: Polling rate (1000 Hz), Debounce (0.1 ms), Battery (94%).
- **Task 3.2:** Implement interactive 75% Keyboard Canvas (`renderer/keyboard.js`):
  - 82 keys with dual Ukrainian/Latin legends from `positions.xml`.
  - Realistic key illumination glow.
  - Multi-select tools: All Keys, WASD + Arrows, Functional, Zones 1-6.
- **Task 3.3:** Implement Chromatic Color Studio (`renderer/color-studio.js`):
  - 16.8M RGB 2D spectrum canvas with live reticle.
  - Direct HEX text input with validation and copy.
  - Discrete R, G, B sliders (0-255).
  - 8 Quick Factory Swatches.
  - 8 Custom User Memory Slots with persistence in `localStorage`.
- **Task 3.4:** Implement Effect & Animation Controls (`renderer/effects.js`):
  - 9 official lighting modes.
  - Stepped Brightness (25%, 50%, 75%, 100%).
  - Stepped Speed (Slow, Medium, Fast).
  - Direction toggle (Left, Right).
  - «Застосувати до клавіатури» and «Зберегти у памʼять EEPROM» action buttons.

### Phase 4: Integration, Packaging & Verification
- **Task 4.1:** Connect UI events to `hator_bridge` via IPC.
- **Task 4.2:** Live hardware test: change colors, switch modes, verify that the physical keyboard reacts in real time.
- **Task 4.3:** Create one-click launch script `start.sh` and desktop shortcut.
- **Task 4.4:** Commit all project code to git.
