# HATOR Icefall PRO Studio - macOS Desktop Architecture & Protocol Specification

- **Date:** 2026-10-30
- **Author:** Antigravity & Данік
- **Status:** Approved Design Specification
- **Target Device:** HATOR Icefall PRO G375 / Icefall 75P Wireless (USB VID: `0x379A` / `0x1A2C`, PID: `0x0920` / `0x413F`, Bluetooth: `Icefall 75P -1`)
- **Target OS:** macOS (Apple Silicon M-series & Intel, macOS 13+)
- **Stitch Project:** `HATOR Icefall PRO Studio - macOS Edition` (`projects/5355054454083714510`)
- **Interactive UI Reference:** `hator_icefall_studio.html`

---

## 1. Executive Summary & Problem Scope

The official Windows software (`HATOR Icefall setup v1.0.0.3.exe`) has two severe deficiencies:
1. **Zero macOS support:** The official software only runs on Windows (32-bit x86 PE executable using the SOUI framework and Win32 HID APIs).
2. **Artificial Color Limitation:** The official software locks lighting to 8 hardcoded color presets (Auto, Red, Green, Blue, Yellow, Magenta, Cyan, White) with no arbitrary color selection, no HEX input, and no continuous RGB color picker.

**HATOR Icefall PRO Studio** solves this completely by delivering a native macOS desktop application with:
- Full 16.8M True RGB Chromatic Color Picker with 2D hue/saturation spectrum, direct HEX input (`#RRGGBB`), and discrete R/G/B sliders (0-255).
- User custom color memory palette (8 quick custom slots).
- Complete reproduction of the 9 official hardware lighting modes with speed, brightness, and direction controls.
- Interactive 75% mechanical keyboard map (82 physical keys + rotary encoder + OLED display) with per-key illumination preview and quick selection filters (All, WASD + Arrows, Functional, Zones 1-6).
- Dual transport communication engine supporting both wired USB HID and Bluetooth wireless connectivity.
- Direct EEPROM flashing to persist lighting configurations across power cycles and reboots.

---

## 2. Reverse-Engineered Hardware Protocol

Static and dynamic analysis of `HATORIcefallKeyboard.exe` (extracted from `HATOR Icefall setup v1.0.0.3.exe`) revealed the exact communication protocols:

### 2.1 Device Identifiers
- **USB Vendor IDs:**
  - `0x379A` (Decimal: 14234) - Hator OEM Vendor ID.
  - `0x1A2C` (Decimal: 6688) - China Resource Semico / Keyceo controller fallback.
- **USB Product IDs:**
  - `0x0920` (Decimal: 2336) - HATOR Icefall PRO G375.
  - `0x413F` (Decimal: 16703) - Keyceo secondary interface.
- **Interface & Usage:**
  - Interface: `1` (Vendor-specific configuration interface, Subdevice 7).
  - Usage Page: `0xFFA0` or `0x0001` (Vendor Defined).
- **Bluetooth Identity:**
  - `Icefall 75P -1` (Address `E2:4A:32:63:1F:CD`).

### 2.2 USB HID Feature Report Protocol (8 Bytes)
All configuration packets sent via `HidD_SetFeature` use an exact 8-byte report buffer:

```
+--------+--------+--------+--------+--------+--------+--------+--------+
| Byte 0 | Byte 1 | Byte 2 | Byte 3 | Byte 4 | Byte 5 | Byte 6 | Byte 7 |
+--------+--------+--------+--------+--------+--------+--------+--------+
| Report | Opcode | Param1 | Param2 | Param3 | Param4 | Param5 | Param6 |
|  0x07  | (Cmd)  | (Mode) |(Bright)|(Speed) | (Dir)  |(Color) | (Sub)  |
+--------+--------+--------+--------+--------+--------+--------+--------+
```

#### Protocol Command Opcodes:
1. **Opcode `0xFA` - Main Lighting Mode & Dynamic Parameters:**
   - `Byte 0`: Report ID = `0x07`.
   - `Byte 1`: Command = `0xFA`.
   - `Byte 2`: Effect Mode ID:
     - `0x01`: Сяйво (Ambilight)
     - `0x02`: Комета (Comet)
     - `0x03`: Хвилі завіси (Curtain)
     - `0x04`: Постійне світло / Мерехтіння (Static / Often bright)
     - `0x05`: Дихання (Breathing)
     - `0x06`: Спектр (Spectroscopy / Cycle)
     - `0x07`: Перегони (Horse racing / Wave)
     - `0x08`: Реакція (Reactive)
     - `0x09`: Власний (Custom Per-Key / Zone)
   - `Byte 3`: Brightness (0, 1, 2, 3 - corresponding to 25%, 50%, 75%, 100%).
   - `Byte 4`: Speed (0 = Slow, 1 = Normal, 2 = Fast).
   - `Byte 5`: Direction (0 = Left, 1 = Right).
   - `Byte 6`: Color Index:
     - `0x00`: Rainbow / Spectrum Auto
     - `0x01`: Red (`#FF0000`)
     - `0x02`: Green (`#00FF00`)
     - `0x03`: Blue (`#0000FF`)
     - `0x04`: Yellow (`#FFFF00`)
     - `0x05`: Magenta (`#FF00FF`)
     - `0x06`: Cyan (`#00FFFF`)
     - `0x07`: White (`#FFFFFF`)
     - `0x08`+: Direct RGB payload stream (in custom mode)
   - `Byte 7`: Checksum / Profile Sub-flag (`0x01` default, or active profile `0x00`=G1, `0x01`=G2, `0x02`=G3).

2. **Opcode `0xFC` - Custom Per-Key & Zone Matrix Stream:**
   - Used in mode `0x09` (Custom).
   - Packet carries zone indexes (Area 1 through Area 6) and per-key RGB coordinates extracted from `positions.xml`.
   - Allows assigning arbitrary 24-bit RGB values (`R`, `G`, `B`) across key groups.

3. **Opcode `0xFB` - EEPROM Flash & Profile Commit:**
   - `Byte 0`: `0x07`.
   - `Byte 1`: `0xFB`.
   - `Byte 2`: Profile ID (`0x00` for G1, `0x01` for G2, `0x02` for G3).
   - `Byte 3`: Action (`0x01` = Commit working memory to onboard Flash).
   - `Bytes 4..7`: Padding zeroes (`0x00`).

---

## 3. Application Architecture & Component Design

The application is structured into four isolated, decoupled layers:

```
+-----------------------------------------------------------------+
|                       macOS Native UI                           |
|       (Tailwind CSS + Lucide Icons + Canvas Color Picker)       |
+-------------------------------+---------------------------------+
                                | IPC Events (preload.js)
+-------------------------------v---------------------------------+
|                    Electron Main Controller                     |
|           - Device Discovery & Hotplug Watcher                  |
|           - Profile & State Management                          |
|           - Preset & Custom Palette Store                       |
+-------------------------------+---------------------------------+
                                | Packet Serializer
+-------------------------------v---------------------------------+
|                    Hardware HID Transport                       |
|           - node-hid (Wired USB Feature Reports)                |
|           - CoreBluetooth / WebBluetooth (Wireless Transport)    |
|           - Retry & Handshake Fallback Engine                   |
+-------------------------------+---------------------------------+
                                | USB / BLE Packets
+-------------------------------v---------------------------------+
|                  HATOR Icefall PRO Hardware                     |
+-----------------------------------------------------------------+
```

### 3.1 Component Specifications

1. **Window Shell (`src/index.html`, `src/renderer.js`):**
   - Translucent obsidian glassmorphism (`#0B0D11`, `backdrop-filter: blur(24px)`).
   - Custom macOS traffic light integration with draggable frameless header.
   - Profile switch tabs: G1 (Default), G2 (Gaming), G3 (Work).
   - Hardware telemetry badge: Connection state (USB 1000Hz / BLE), Battery percentage, Polling rate, Debounce delay.

2. **Interactive 75% Keyboard Canvas (`src/components/keyboard-canvas.js`):**
   - Renders all 82 keys in the standard ANSI 75% layout based on `positions.xml`.
   - Displays bilingual Cyrillic (Ukrainian) and Latin legends on keycaps.
   - Displays the functional rotary encoder knob and OLED screen widget.
   - Per-key click and multi-select drag selection:
     - Group filters: All Keys, WASD + Arrows, Functional (F1-F12 + Nav), Zones 1-6.
   - Real-time CSS lighting glow reflecting selected effect and colors.

3. **Color Studio & Inspector (`src/components/color-studio.js`):**
   - 2D Hue/Saturation chromatic color canvas with precision interactive reticle.
   - Direct HEX color input (`#RRGGBB`) with regex validation and clipboard copy.
   - Interactive R, G, B channel sliders (0-255).
   - 8 Quick Factory Swatches.
   - 8 Persistent User Custom Memory Slots with local storage saving.

4. **Lighting Mode Controller (`src/components/lighting-modes.js`):**
   - Dropdown with all 9 modes with Ukrainian naming.
   - Stepped Brightness control: 25%, 50%, 75%, 100%.
   - Stepped Speed control: Slow, Normal, Fast.
   - Direction toggle: Left vs Right.
   - Buttons: «Застосувати до клавіатури» (Immediate test) and «Зберегти у пам'ять EEPROM» (Permanent flash).

5. **HID Driver Module (`src/driver/hator-hid.js`):**
   - Communicates with the keyboard via `node-hid` (HID Feature Reports) or WebHID.
   - Automatically detects device attachment and detachment (hotplug).
   - Assembles 8-byte feature report buffers and dispatches to the device.

---

## 4. Error Handling & Edge Cases

| Scenario | Detection | Fallback / Recovery |
| :--- | :--- | :--- |
| **Keyboard disconnected** | `node-hid` device removal event or write error | UI switches to "Від'єднано" status badge, disables hardware flash buttons, continues in offline mockup mode |
| **USB permission denied** | macOS permission prompt or EACCES error | Prompts user with instruction to grant input monitoring / HID permissions in macOS System Settings |
| **Invalid HEX input** | Regex test `/^#?[0-9A-Fa-f]{6}$/` fails | Retains previous valid color, highlights input with subtle warning ring |
| **Rapid slider dragging** | Hundreds of change events per second | Debounces packet transmission to 20ms intervals (50 updates/sec maximum) to prevent USB buffer overrun |
| **Firmware communication timeout** | Feature report fails after 3 retries | Re-enumerates HID devices, alerts user with non-blocking toast notification |

---

## 5. Verification & Testing Protocol

1. **Unit Testing:**
   - Packet builder test: Verify that `buildLightingPacket(mode, brightness, speed, direction, color)` produces exact 8-byte buffer matching `HATORIcefallKeyboard.exe` disassembly.
   - HEX and RGB conversion: Verify bi-directional consistency across `#000000` to `#FFFFFF`.
2. **Hardware Integration Testing:**
   - Connect HATOR Icefall PRO G375 via USB.
   - Verify detection via `node-hid`.
   - Dispatch `0xFA` packets with modes 1 to 9, verifying that physical LEDs change mode, brightness, speed, and direction.
   - Dispatch custom color packets, verifying that physical keys reflect chosen RGB colors.
   - Dispatch `0xFB` commit packet, power-cycle the keyboard (unplug/replug), and verify settings persist.
3. **UI / UX Testing:**
   - Verify layout responsiveness on macOS Retina displays (1x and 2x pixel ratio).
   - Verify smooth 60fps animations for keyboard canvas lighting preview.
