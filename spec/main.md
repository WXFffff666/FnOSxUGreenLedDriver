# FnUGreenLed — Development Specification

## Overview

FnUGreenLed is a native fnOS application that provides LED indicator control for UGREEN NAS devices. It lets users control front-panel LEDs for power, network, and disk bays through a skeuomorphic web interface, with per-LED modes for off, solid on, and automatic activity indication.

## Project History

### Version 1 — App.Native.LEDController

The initial prototype was built as `App.Native.LEDController` (v1.0.0), manually assembled without the fnpack CLI tool. It established the core architecture:

- **CGI backend** (`app/server/index.cgi`): Python 3 CGI script handling GET (serve HTML) and POST (LED control API) requests
- **Frontend** (separated files): `app/ui/index.html` (structure), `app/www/css/style.css` (styling), `app/www/js/app.js` (interaction logic)
- **Desktop entry**: iframe-based integration via `/cgi/ThirdParty/App.Native.LEDController/index.cgi/`
- **Driver dependency**: Relies on `ugreen_leds_cli` from [miskcoo/ugreen_leds_controller](https://github.com/miskcoo/ugreen_leds_controller)

This version was functional but did not follow fnOS packaging standards — it was hand-assembled rather than using `fnpack create` / `fnpack build`.

### Version 2 — FnUGreenLed (Current)

Rebuilt from scratch using `fnpack create` to generate a standards-compliant project structure, then migrated all features from V1 with improvements:

- **Self-hosted HTTP server** (`app/server/main.py`): Python HTTP server (instead of CGI), serves embedded HTML/CSS/JS and JSON API
- **Bundled LED driver**: Static x86_64 binary of `ugreen_leds_cli` cross-compiled via Docker (Alpine Linux, musl-g++) and included in the package
- **Desktop entry**: Standard `type: "url"` with port 19580 to avoid common 8080 conflicts
- **Process management**: Full `cmd/main` lifecycle (start/stop/status) managing the Python server
- **System integration**: `usr-local-linker` symlinks the bundled CLI to `/usr/local/bin/`
- Error handling updated to fnOS V1.1.8+ conventions
- Built and packaged with `fnpack build` → `FnUGreenLed-1.1.0.x86_64.fpk`

### Version 2.1 — FnUGreenLed v1.1.0 (Current Working Tree)

The current uncommitted code expands the app from fixed DXP4800 manual control into a multi-bay controller:

- **Three LED modes**: `off`, `on`, and `auto`
- **State persistence**: Saves LED modes to `TRIM_PKGVAR/led_state.json` and restores them on service start
- **LED probing**: Uses `ugreen_leds_cli all -status` to detect available LEDs and read current hardware modes
- **Model probing**: Uses DMI product name (`dmidecode --string system-product-name` or `/sys/class/dmi/id/product_name`) to infer known UGREEN model families
- **Dynamic UI**: Renders disk bays according to detected or configured disk count
- **Configuration API**: `POST /api/config` can switch disk count manually
- **Reset API**: `POST /api/reset` clears local config/state and returns the app to the initialization page
- **Status API**: `GET /api/status` exposes current modes, activity state, detected disk map, and selected network interface
- **Activity monitoring**: Auto mode polls `/sys/class/net/*/statistics` and `/sys/block/*/stat`
- **Disk mapping**: Uses ATA mapping by default and applies the upstream DXP6800 slot order override

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  fnOS Desktop                         │
│  ┌────────────────────────────────────────────────┐  │
│  │  Browser (new tab)                              │  │
│  │  ┌──────────────────────────────────────────┐  │  │
│  │  │  http://127.0.0.1:19580                   │  │  │
│  │  │  ┌─────────────────────────────────┐     │  │  │
│  │  │  │  main.py (Python HTTP Server)   │     │  │  │
│  │  │  │  GET  /     → Embedded HTML/CSS/JS   │  │  │
│  │  │  │  POST /api/control → JSON API  │     │  │  │
│  │  │  └────────────┬────────────────────┘     │  │  │
│  │  └───────────────│──────────────────────────┘  │  │
│  └──────────────────│─────────────────────────────┘  │
│                     │ subprocess                       │
│                     ▼                                  │
│  ┌─────────────────────────────────────────────────┐  │
│  │  ugreen_leds_cli (static x86_64 binary)         │  │
│  │  Bundled: /var/apps/FnUGreenLed/target/server/  │  │
│  │  Symlink: /usr/local/bin/ugreen_leds_cli        │  │
│  └─────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

## Features

| Feature | Description |
|---------|-------------|
| Power LED control | Set power indicator to off/on/auto |
| Network LED control | Set network indicator to off/on/auto; auto follows network traffic |
| Disk bay LED control | Independently set each detected/configured disk bay indicator |
| Batch all-on | Set all LEDs to solid on |
| Batch all-auto | Set all LEDs to automatic mode |
| Batch all-off | Turn all LEDs off |
| State persistence | Restore saved LED modes on service start |
| Dynamic disk count | Detect or manually configure 1-8 disk bays |
| Hardware state import | Prefer `ugreen_leds_cli all -status` over persisted local state when available |
| Model-assisted mapping | Uses DMI product name to pick known disk count and ATA mapping |
| Reset configuration | Clear local config/state and re-enter initialization |
| Visual feedback | Skeuomorphic toggle switches with LED glow animation |
| Toast notifications | Success/error messages with auto-dismiss |

## API Specification

### POST `http://127.0.0.1:19580/api/control`

**Request:**
```json
{
    "led": "power|netdev|disk1|disk2|...",
    "action": "off|on|auto"
}
```

**Response (success):**
```json
{
    "success": true,
    "message": "power → 常亮"
}
```

**Response (error):**
```json
{
    "success": false,
    "message": "无效指示灯: panel"
}
```

### GET `http://127.0.0.1:19580/api/status`

Returns persisted modes, current auto-mode activity flags, disk map, network interface, and active LED list.

### POST `http://127.0.0.1:19580/api/all/off|on|auto`

Batch-sets every active LED.

### GET/POST `http://127.0.0.1:19580/api/config`

Reads or updates disk count configuration:

```json
{
    "disk_count": 6,
    "model": "manual"
}
```

### POST `http://127.0.0.1:19580/api/reset`

Clears local configuration and persisted LED modes:

- `TRIM_PKGVAR/device_config.json`
- `TRIM_PKGVAR/led_state.json`

After reset, `GET /` returns the initialization page until the user saves a new disk count.

### GET `http://127.0.0.1:19580/`

Returns the initialization page when no local config exists; otherwise returns the self-contained control page with embedded CSS and JavaScript.

## LED Mapping

| LED ID | Physical Indicator | Description |
|--------|-------------------|-------------|
| `power` | Front panel power LED | Device power status |
| `netdev` | Front panel network LED | Network activity |
| `disk1` | Bay 1 LED | Disk slot 1 |
| `disk2` | Bay 2 LED | Disk slot 2 |
| `disk3` | Bay 3 LED | Disk slot 3 |
| `disk4` | Bay 4 LED | Disk slot 4 |
| `disk5`-`disk8` | Bay 5-8 LED | Present when detected/configured on larger models |

## UI Design

Skeuomorphic design mimicking the UGREEN DXP4800 NAS physical chassis:

- **Color palette**: Dark metallic case (#2a2a2a–#3d3d3d), green LEDs (#00ff88 with glow effect)
- **Components**: 
  - Header bar with checkmark icon and pulsing status dot
  - Power/Network section with large toggle switches
  - 4-bay disk grid with numbered bays, disk icons, and compact toggle switches
  - Footer action bar with "全部开启" (all on) and "全部关闭" (all off) buttons
- **Interactions**: Hover lift effects, press depression, smooth toggle animations, toast notifications
- **Responsive**: Adapts to tablet and mobile widths

## Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python 3 | ≥3.6 | CGI runtime |
| GCC | any | Compile LED driver (install-time only) |
| Git | any | Clone LED driver repo (install-time only) |
| [ugreen_leds_cli](https://github.com/miskcoo/ugreen_leds_controller) | latest | LED hardware control binary |

## Project Structure (fnpack standard)

```
FnUGreenLed/
├── app/
│   ├── server/
│   │   ├── main.py             # Python HTTP server (embedded HTML/CSS/JS + API)
│   │   └── ugreen_leds_cli     # Static x86_64 LED driver binary
│   └── ui/
│       ├── config              # Desktop entry (url → port 19580)
│       └── images/
│           ├── icon_64.png     # 64×64 UI icon
│           └── icon_256.png    # 256×256 UI icon
├── cmd/
│   ├── main                    # Lifecycle: start/stop/status (Python server process)
│   ├── install_init            # Setup hook
│   ├── install_callback        # Post-install hook
│   ├── uninstall_init          # Pre-uninstall hook
│   ├── uninstall_callback      # Post-uninstall hook
│   ├── upgrade_init            # Pre-upgrade hook
│   ├── upgrade_callback        # Post-upgrade hook
│   ├── config_init             # Pre-config-change hook
│   └── config_callback         # Post-config-change hook
├── config/
│   ├── privilege               # run-as: root (hardware I2C access)
│   └── resource                # data-share + usr-local-linker
├── wizard/                     # User interaction wizards (empty)
├── manifest                    # App metadata (service_port=19580)
├── ICON.PNG                    # 64×64 App Center icon
└── ICON_256.PNG                # 256×256 App Center icon
```

## Manifest Configuration

| Field | Value | Rationale |
|-------|-------|-----------|
| `appname` | FnUGreenLed | Unique app identifier |
| `version` | 1.1.0 | Semantic versioning |
| `display_name` | 指示灯控制 | Chinese display name |
| `service_port` | 19580 | HTTP server listening port |
| `desktop_uidir` | ui | Standard UI directory |
| `desktop_applaunchname` | FnUGreenLed.Application | Matches entry key in `app/ui/config` |

## Privilege Configuration

- `run-as: root` — Required for direct hardware (I2C bus) access to LED controller chip at address 0x3a
- Custom user/group: `ledcontroller` / `ledcontroller`

## Known Limitations

1. **Hardware truth is write-biased**: The app persists requested LED modes, but `ugreen_leds_cli` is still primarily a write tool; true hardware state can diverge if changed outside the app
2. **Auto mode is heuristic**: Disk and network activity are inferred from Linux `/sys` counters
3. **Model detection is not complete**: Current code detects available disk LEDs; full DMI/SMBIOS model matching remains roadmap work
4. **No authentication**: API endpoint has no authentication beyond the fnOS desktop session
5. **x86_64 only**: Compiled driver targets x86 architecture; ARM NAS models are not supported
