# Hator Skyfall OS - macOS Desktop Studio & Hardware Protocol Specification

- **Date:** 2026-10-30
- **Author:** Antigravity Engineering & Данік
- **Status:** Approved Design Specification
- **Target Device:** Hator Skyfall 80 Pro Wireless (HTK4180 / HTK4180UA / HTK4180EU)
- **Target OS:** macOS (Apple Silicon / Intel, macOS 14+)

---

## 1. Executive Summary & Problem Statement

Hator provides keyboard configuration software exclusively for Microsoft Windows. macOS users of the Hator Skyfall 80 Pro Wireless (and related Yichip YC3123-based keyboards) lack native software to configure per-key RGB backlighting, custom key mappings (notably Command/Option layout switching for Mac), rotary knob actions, onboard flash profiles, and the integrated 128x128 square OLED/TFT display.

This project delivers **Hator Skyfall OS**: a native, frameless macOS desktop application built with Electron and direct WebHID protocol integration, faithfully embodying the Swiss brutalist-minimalist design language of Blitzkrieg OS (100% monochrome palette `#000000`, 1px hairline borders `#1F1F22`, crisp white typography, and electric violet `#6056F0` keycap backlighting).

---

## 2. Reverse-Engineered Hardware Profile

Through static analysis of Hator's official WebHID driver (`https://hator.io/js/index.8a6dc9e2.js`) and macOS bus telemetry (`system_profiler SPBluetoothDataType SPUSBDataType`), the exact hardware profile is defined:

| Parameter | Specification |
| :--- | :--- |
| **Keyboard Model** | Hator Skyfall 80 Pro Wireless (SKU: `HTK4180`, `HTK4180UA`, `HTK4180EU`) |
| **System-on-Chip (SoC)** | Yichip YC3123 (`yc3123_k2505_soc`), 32-bit ARM Cortex tri-mode (USB-C, 2.4G RF, Bluetooth 5.0) |
| **USB Vendor ID (VID)** | `0x379A` (Decimal: 14234) |
| **USB Product ID (PID)** | `0x1806` (Decimal: 6150) / `0x1805` (Decimal: 6149) |
| **Bluetooth Identity** | `Icefall 75P -1` (Device Address: `E2:4A:32:63:1F:CD`), Minor Type: `Keyboard` |
| **Layout ID** | `Common82_K2505` (75% Exploded ANSI, 82 physical keys + Rotary Encoder + Square Display) |
| **Display Specifications** | 1:1 Geometric Square OLED/TFT (`size: {w: 128, h: 128}`), RGB565 / 16-bit color mode |
| **Onboard Profiles** | 4 hardware layers (`layer: 4, fnSysLayer: {win: 1, mac: 1}`) with EEPROM persistence |
| **Rotary Encoder** | Tri-action knob: Rotate Left (`AudioVolumeDown`), Rotate Right (`AudioVolumeUp`), Click (`AudioVolumeMute`) |

---

## 3. Communication Protocol Architecture

Communication with the YC3123 controller occurs strictly via 64-byte USB HID Feature Reports and Output Reports (`reportCount: 64`, Report ID `0x05` / `0x06` or Vendor Usage Page `0xFFA0`):

```
+-----------+------------+--------------------+--------------------------------+
| Byte 0    | Byte 1     | Bytes 2..63        | Description                    |
+-----------+------------+--------------------+--------------------------------+
| Report ID | Command ID | Payload Data (N B) | Zero-padded to 64 bytes total  |
| 0x05/0x06 | (Opcode)   |                    |                                |
+-----------+------------+--------------------+--------------------------------+
```

### Protocol Opcode Definitions:
1. **Status & Handshake (`0x01` / `0x02`):**
   - Queries hardware firmware revision, active layer (1-4), current connection transport (USB vs BT), and battery level.
2. **RGB Lighting Control (`0x0B`):**
   - Controls matrix brightness, effect modes, and per-key color assignments.
   - Electric violet backlight payload: `#6056F0` (`R: 96, G: 86, B: 240`) broadcast to all 82 LED channels.
3. **Key Remapping & Modifier Swapping (`0x07` / `0x08`):**
   - Transmits keycode translation table to layer memory.
   - Default macOS profile assigns physical `Win` key to `Option` (`0xE2`) and physical `Alt` key to `Command` (`0xE3`).
4. **Rotary Encoder Remapping (`0x14`):**
   - Assigns custom HID consumer or macro events to rotary CCW, CW, and push actions.
5. **OLED / TFT Frame Streaming (`0x12`):**
   - Chunks 128x128 image frames into sequential 64-byte packets.
   - Supports static monochrome/color bitmap upload and real-time telemetry rendering (Clock, CPU, Volume level).
6. **EEPROM Commit (`0x0F`):**
   - Writes the active working memory configuration permanently into the YC3123 onboard flash.

---

## 4. Application Architecture & Visual System

### 4.1 Technology Stack
- **Runtime:** Electron v33+ with Node.js v26.
- **Frontend Layer:** HTML5, Vanilla JavaScript (ESM), Tailwind CSS design tokens, JetBrains Mono & Inter typography.
- **Hardware Bridge:** WebHID (`navigator.hid`) inside Electron Renderer, coordinated via Electron Main process session permission filters.
- **Packaging:** Native macOS `.app` bundle with ad-hoc signing.

### 4.2 Frameless Window Geometry
- Locked to 1728px x 1080px desktop canvas (`width: 1728, height: 1080, resizable: false, frame: false`).
- Frameless command header with custom geometric controls (Minimize `-`, Maximize `□`, Close `×`).
- Strict 100% monochrome theme:
  - Page Background: `#000000`
  - Panel Backgrounds: `#070708`, `#0C0D0E`, `#111214`
  - Dividing Hairlines: `1px solid #1F1F22`
  - Primary Text: `#FFFFFF`
  - Muted Labels: `#8E9299`, `#6E737B`, `#454A51`
  - Keycap Backlight Outline: `#6056F0` (with `0 0 7px rgba(96, 86, 240, 0.4)` glow)

### 4.3 State Management & Screens
The application functions as a finite state machine with two core views:

```dot
digraph StateMachine {
    rankdir=LR;
    node [shape=box, style=filled, fillcolor="#0C0D0E", fontname="JetBrains Mono", fontcolor="#FFFFFF", color="#1F1F22"];
    edge [fontname="JetBrains Mono", fontsize=10, color="#8E9299", fontcolor="#8E9299"];

    Standby [label="STANDBY GATEWAY\n(No device on IOKit/BT)"];
    Studio [label="CONNECTED STUDIO\n(YC3123 Handshake OK)"];

    Standby -> Studio [label="HID Connect Event\n(VID: 0x379A)"];
    Studio -> Standby [label="HID Disconnect Event\n(Unplug / Sleep)"];
}
```

1. **Standby Gateway Screen:**
   - Visual: Pulsing architectural 1px dashed wireframe of the 75% chassis, metallic rotary knob, and square display.
   - Diagnostics: Live diagnostic terminal displaying continuous IOKit and CoreBluetooth polling records.
   - Interactive: "FORCE IOKIT SCAN" manual trigger.
   - Spec Mockup: `file:///Users/daniildusinskij/.gemini/antigravity/brain/a876e1ad-71bb-40e8-80a7-642c8b69de07/hator_skyfall_standby_screen.html`.

2. **Connected Studio Screen:**
   - Visual: Complete interactive 82-key matrix.
   - Keycaps: Dual English (`#FFFFFF`) / Cyrillic Ukrainian (`#6E737B`) legends.
   - Function Row: Clean `F1` through `F12` keys with all emoji clutter removed.
   - Display Widget: 1:1 geometric square preview (`46px × 46px` UI, 128×128 hardware) with clock/telemetry sync.
   - Encoder Widget: Metallic radial knob with directional control bindings.
   - Backlight: Electric violet `#6056F0` neon perimeter border.
   - Spec Mockup: `file:///Users/daniildusinskij/.gemini/antigravity/brain/a876e1ad-71bb-40e8-80a7-642c8b69de07/hator_skyfall_os_screen.html`.

---

## 5. Security & Permission Model

- **No Root / Sudo:** The application executes under standard macOS user permissions via standard IOKit user client interfaces.
- **WebHID Isolation:** Electron's session permissions grant access exclusively to Vendor ID `0x379A` and Bluetooth HID keyboards. No arbitrary USB device access is permitted.
- **Safe Flashing:** All onboard flash writes require explicit user confirmation via the "COMMIT TO ONBOARD EEPROM" command to prevent accidental write cycles.

---

## 6. Verification & Testing Plan

1. **Device Discovery Test:**
   - Plug in keyboard via USB-C -> Verify transition from Standby Gateway to Connected Studio within 500ms.
   - Unplug USB-C -> Verify transition back to Standby Gateway without application freeze or crash.
2. **Bluetooth Connection Test:**
   - Connect via Bluetooth (`Icefall 75P -1`) -> Verify device recognized and telemetry reported.
3. **RGB Lighting Test:**
   - Toggle backlight state -> Verify all 82 switches illuminate in electric violet (`#6056F0`).
4. **Key Remapping Test:**
   - Set Win/Alt to Option/Command -> Verify keypresses in macOS Terminal register correctly as `Option` and `Command`.
5. **128x128 OLED Test:**
   - Send clock / status stream -> Verify 128x128 screen updates accurately.
