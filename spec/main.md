# FnUGreenLed — Development Specification

## Overview

FnUGreenLed is a native fnOS application that provides LED indicator control for UGREEN DXP4800 series NAS devices. It enables users to independently toggle all 6 front-panel LEDs (power, network, and 4 disk bays) through a skeuomorphic web interface that visually mimics the physical NAS chassis.

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
- **Desktop entry**: Standard `type: "url"` with port 8080 (matches fnpack template pattern)
- **Process management**: Full `cmd/main` lifecycle (start/stop/status) managing the Python server
- **System integration**: `usr-local-linker` symlinks the bundled CLI to `/usr/local/bin/`
- Error handling updated to fnOS V1.1.8+ conventions
- Built and packaged with `fnpack build` → `FnUGreenLed-1.0.0.x86_64.fpk`

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  fnOS Desktop                         │
│  ┌────────────────────────────────────────────────┐  │
│  │  Browser (new tab)                              │  │
│  │  ┌──────────────────────────────────────────┐  │  │
│  │  │  http://127.0.0.1:8080                    │  │  │
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
| Power LED control | Toggle power indicator on/off |
| Network LED control | Toggle network activity indicator on/off |
| Disk bay LED control (×4) | Independently toggle each disk bay indicator |
| Batch all-on | Turn all 6 LEDs on simultaneously |
| Batch all-off | Turn all 6 LEDs off simultaneously |
| Visual feedback | Skeuomorphic toggle switches with LED glow animation |
| Toast notifications | Success/error messages with auto-dismiss |

## API Specification

### POST `http://127.0.0.1:8080/api/control`

**Request:**
```json
{
    "led": "power|netdev|disk1|disk2|disk3|disk4",
    "action": "on|off"
}
```

**Response (success):**
```json
{
    "success": true,
    "message": "power 已开启"
}
```

**Response (error):**
```json
{
    "success": false,
    "message": "无效的指示灯: panel"
}
```

### GET `http://127.0.0.1:8080/`

Returns the self-contained HTML application page with embedded CSS and JavaScript.

## LED Mapping

| LED ID | Physical Indicator | Description |
|--------|-------------------|-------------|
| `power` | Front panel power LED | Device power status |
| `netdev` | Front panel network LED | Network activity |
| `disk1` | Bay 1 LED | Disk slot 1 |
| `disk2` | Bay 2 LED | Disk slot 2 |
| `disk3` | Bay 3 LED | Disk slot 3 |
| `disk4` | Bay 4 LED | Disk slot 4 |

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
│       ├── config              # Desktop entry (url → port 8080)
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
├── manifest                    # App metadata (service_port=8080)
├── ICON.PNG                    # 64×64 App Center icon
└── ICON_256.PNG                # 256×256 App Center icon
```

## Manifest Configuration

| Field | Value | Rationale |
|-------|-------|-----------|
| `appname` | FnUGreenLed | Unique app identifier |
| `version` | 1.0.0 | Semantic versioning |
| `display_name` | 指示灯控制 | Chinese display name |
| `service_port` | 8080 | HTTP server listening port |
| `desktop_uidir` | ui | Standard UI directory |
| `desktop_applaunchname` | FnUGreenLed.Application | Matches entry key in `app/ui/config` |

## Privilege Configuration

- `run-as: root` — Required for direct hardware (I2C bus) access to LED controller chip at address 0x3a
- Custom user/group: `ledcontroller` / `ledcontroller`

## Known Limitations

1. **LED state is not persistent**: The `ugreen_leds_cli` tool does not expose a read-status command, so the UI always starts with all LEDs shown as "off" regardless of actual hardware state
2. **Single device support**: Hardcoded for DXP4800 with exactly 4 disk bays
3. **No authentication**: API endpoint has no authentication beyond the fnOS desktop session
4. **x86_64 only**: Compiled driver targets x86 architecture; ARM NAS models not supported
