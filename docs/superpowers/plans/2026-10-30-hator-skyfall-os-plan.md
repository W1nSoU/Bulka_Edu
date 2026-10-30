# Implementation Plan: Hator Skyfall OS (macOS Desktop Studio & YC3123 Driver)

- **Date:** 2026-10-30
- **Spec:** [`docs/superpowers/specs/2026-10-30-hator-skyfall-os-design.md`](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-10-30-hator-skyfall-os-design.md)
- **Target Directory:** `/Users/daniildusinskij/All/Dev/hator-skyfall-os`
- **Target Architecture:** Electron v33+ + Node.js v26 + Chromium WebHID + Vanilla ESM Frontend

---

## Technical Context & Confirmed Hardware Telemetry

- **Target Device:** Hator Skyfall 80 Pro Wireless (HTK4180 / HTK4180UA / HTK4180EU)
- **SoC:** Yichip YC3123 (`yc3123_k2505_soc`), 32-bit ARM Cortex Tri-mode controller.
- **Vendor ID:** `0x379A` (14234)
- **Product IDs:** `0x1806` (6150), `0x1805` (6149), `0x0920`, `0x3904`
- **Bluetooth Identity:** `Icefall 75P -1` (Address: `E2:4A:32:63:1F:CD`)
- **Packet Structure:** 64-byte raw HID report (Report ID: `0x06` or `0x05`, Endpoint: `0x02`, Ack: `0x82`):
  - `0x14`: Handshake / Ping / Device Init
  - `0x15`: System State & Battery Telemetry
  - `0x18`: Key Remapping Matrix (82-key ANSI layout with Mac modifier swap)
  - `0x1A`: RGB Matrix LED streaming (Electric violet `#6056F0`)
  - `0x12`: 128x128 1:1 Square OLED / TFT display packet chunker

---

## Tasks & Execution Phases

### Phase 1: Workspace Scaffolding & Dependencies
1. **Initialize Application Directory:**
   - Create project directory `/Users/daniildusinskij/All/Dev/hator-skyfall-os`.
   - Setup `package.json` with `electron` runtime, development scripts (`npm start`, `npm run pack`), and ESM project configuration.
   - Configure `.gitignore` for `node_modules/`, `dist/`, `.DS_Store`, and temporary test logs.

### Phase 2: Electron Main Process & Native macOS Integration
2. **Implement Main Process (`main.js`):**
   - Create frameless desktop viewport locked to `1728px × 1080px` (`width: 1728, height: 1080, resizable: false, frame: false, titleBarStyle: 'hidden'`).
   - Configure WebHID permissions via `session.defaultSession.setDevicePermissionHandler` and `session.defaultSession.on('select-hid-device')` for automatic, promptless connection to `0x379A` devices.
   - Implement IPC handlers for frameless window actions (Minimize, Maximize/Toggle, Close) and IOKit hardware scanning.

### Phase 3: Hardware Protocol Engine (`src/protocol/`)
3. **Implement Packet Builder & Serialization (`src/protocol/yc3123.js`):**
   - Implement 64-byte packet constructor with zero-padding and opcode validation.
   - Implement Handshake & Ping (`0x14`).
   - Implement Status & Battery query (`0x15`).
   - Implement Key Remapping Matrix (`0x18`) with default macOS layout (Cmd/Opt swapped for native Apple keyboard shortcuts).
   - Implement RGB Backlight Controller (`0x1A`): static violet `#6056F0`, brightness levels, breathing animation.
   - Implement 128x128 Square OLED stream chunker (`0x12`): slice RGB565 bitmaps into sequential 64-byte payload frames.

### Phase 4: User Interface & State Management (`src/ui/`)
4. **Implement Dual-Screen Layout & Transition Engine:**
   - Integrate approved Blitzkrieg OS visual system (Swiss brutalist-minimalist, 100% monochrome, 1px `#1F1F22` borders).
   - **State 1 - Standby Gateway Screen:**
     - Pulsing 1px dashed wireframe silhouette of the 75% chassis, knob, and 1:1 square display.
     - Live diagnostic terminal with simulated/real IOKit & Bluetooth polling stream (`[IOKIT_POLL]`, `[CORE_BT]`).
     - "FORCE IOKIT SCAN" interactive trigger.
   - **State 2 - Connected Studio Screen:**
     - 82-key matrix with dual English (`#FFFFFF`) and Ukrainian Cyrillic (`#6E737B`) legends.
     - Clean `F1`-`F12` keys without emoji clutter.
     - Electric violet `#6056F0` neon perimeter glow.
     - 1:1 Geometric Square OLED (`46px × 46px` UI, 128x128 hardware) with real-time clock and telemetry preview.
     - Rotary metallic encoder widget with directional event bindings.
     - Key remapping drawer with "COMMIT TO ONBOARD FLASH" action.

### Phase 5: Verification, Standalone Launcher & Documentation
5. **Implement Launcher Script & Verification:**
   - Write executable `start.sh` that checks dependencies, installs Electron if needed, and launches the studio.
   - Run protocol packet generation unit tests.
   - Verify seamless transition between Standby and Connected states.
   - Commit complete code to local git repository.
