#!/usr/bin/env python3
"""
FnUGreenLed v1.3 — LED Controller for UGREEN NAS
- Three LED states: off / solid on / auto (responsive blink)
- Disk I/O monitoring via /sys/block/*/stat
- Network traffic monitoring via /sys/class/net/*/statistics
- Multi-device support with auto-detection
"""

import os
import secrets
import json
import subprocess
import threading
import time
import glob
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

VALID_MODES = ['off', 'on', 'auto']
MAX_DISK_LEDS = 8
LED_BASE = ['power', 'netdev']
LED_STATUS_RE = re.compile(
    r'^(?P<led>power|netdev|disk[1-8]): status = (?P<status>off|on|blink|breath), '
    r'brightness = (?P<brightness>\d+), color = RGB\((?P<r>\d+), (?P<g>\d+), (?P<b>\d+)\)'
)
MODEL_PROFILES = [
    ('DXP6800', {'id': 'dxp6800pro', 'name': 'DXP6800 series', 'disk_count': 6,
                 'ata_map': ['ata3', 'ata4', 'ata5', 'ata6', 'ata1', 'ata2']}),
    ('DXP8800', {'id': 'dxp8800plus', 'name': 'DXP8800 series', 'disk_count': 8,
                 'ata_map': ['ata1', 'ata2', 'ata3', 'ata4', 'ata5', 'ata6', 'ata7', 'ata8']}),
    ('DXP4800Plus', {'id': 'dxp4800plus', 'name': 'DXP4800 Plus series', 'disk_count': 4,
                     'ata_map': ['ata1', 'ata2', 'ata3', 'ata4']}),
    ('DXP4800 Plus', {'id': 'dxp4800plus', 'name': 'DXP4800 Plus series', 'disk_count': 4,
                      'ata_map': ['ata1', 'ata2', 'ata3', 'ata4']}),
    ('DXP4800', {'id': 'dxp4800', 'name': 'DXP4800 series', 'disk_count': 4,
                 'ata_map': ['ata1', 'ata2', 'ata3', 'ata4']}),
    ('DXP2800', {'id': 'dxp2800', 'name': 'DXP2800 series', 'disk_count': 2,
                 'ata_map': ['ata1', 'ata2']}),
    ('DX4600', {'id': 'dx4600pro', 'name': 'DX4600 series', 'disk_count': 4,
                'ata_map': ['ata1', 'ata2', 'ata3', 'ata4']}),
    ('DX4700', {'id': 'dx4700plus', 'name': 'DX4700 series', 'disk_count': 4,
                'ata_map': ['ata1', 'ata2', 'ata3', 'ata4']}),
]

_BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ugreen_leds_cli')
CLI = _BUNDLED if os.path.exists(_BUNDLED) else '/usr/local/bin/ugreen_leds_cli'
PORT = int(os.environ.get('TRIM_SERVICE_PORT', 19580))
VAR = os.environ.get('TRIM_PKGVAR', '/tmp')
STATE_FILE = os.path.join(VAR, 'led_state.json')
CONFIG_FILE = os.path.join(VAR, 'device_config.json')

BLINK_ON_MS = 80
BLINK_OFF_MS = 120
MONITOR_INTERVAL = 0.5  # seconds

AUTH_FILE = os.path.join(VAR, 'auth_token.json')

# ── helpers ──────────────────────────────────────────────

def run(*args):
    try:
        r = subprocess.run([CLI] + list(args), capture_output=True, text=True, timeout=5)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return False, '', f'CLI not found: {CLI}'
    except Exception as e:
        return False, '', str(e)

def run_cmd(*args):
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=5)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return False, '', str(e)

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return default

def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f)
    except IOError:
        pass

def remove_file(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except IOError as e:
        return str(e)
    return None

def check_auth(headers):
    token = headers.get('X-Auth-Token', '')
    return token == auth_cfg.get('token', '')

# ── hardware probe ───────────────────────────────────────

def led_status_to_mode(status):
    if status == 'off':
        return 'off'
    if status == 'on':
        return 'on'
    if status in ('blink', 'breath'):
        return 'auto'
    return 'off'

def parse_led_status(text):
    statuses = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or 'unavailable or non-existent' in line:
            continue
        m = LED_STATUS_RE.match(line)
        if not m:
            continue
        led = m.group('led')
        statuses[led] = {
            'status': m.group('status'),
            'mode': led_status_to_mode(m.group('status')),
            'brightness': int(m.group('brightness')),
            'color': [int(m.group('r')), int(m.group('g')), int(m.group('b'))],
        }
    return statuses

def probe_leds():
    ok, out, err = run('all', '-status')
    if ok:
        statuses = parse_led_status(out)
        if statuses:
            return statuses, ''

    # Fallback for older or partially working CLI behavior.
    statuses = {}
    for led in LED_BASE + [f'disk{i}' for i in range(1, MAX_DISK_LEDS + 1)]:
        ok, out, _ = run(led, '-status')
        if ok:
            parsed = parse_led_status(out)
            if led in parsed:
                statuses[led] = parsed[led]
            elif 'unavailable' not in out and 'non-existent' not in out:
                statuses[led] = {'status': 'off', 'mode': 'off', 'brightness': 0, 'color': [0, 0, 0]}
    return statuses, err

def disk_count_from_leds(statuses):
    disk_nums = []
    for led in statuses:
        m = re.match(r'^disk([1-8])$', led)
        if m:
            disk_nums.append(int(m.group(1)))
    return max(disk_nums) if disk_nums else 0

def detect_model():
    candidates = []
    ok, out, _ = run_cmd('dmidecode', '--string', 'system-product-name')
    if ok and out:
        candidates.append(out.strip())
    for path in ('/sys/class/dmi/id/product_name', '/sys/devices/virtual/dmi/id/product_name'):
        try:
            with open(path) as f:
                value = f.read().strip()
            if value:
                candidates.append(value)
        except IOError:
            pass

    product = candidates[0] if candidates else ''
    for prefix, profile in MODEL_PROFILES:
        if product.startswith(prefix):
            data = dict(profile)
            data['product_name'] = product
            return data
    return {'id': 'auto', 'name': product or 'Unknown', 'disk_count': 0, 'ata_map': [], 'product_name': product}

# ── disk & network detection ─────────────────────────────

def block_device_info(sdp):
    dev = os.path.basename(sdp)
    real = os.path.realpath(sdp)
    ata = None
    hctl = None
    m = re.search(r'/ata(\d+)/', real)
    if m:
        ata = f'ata{m.group(1)}'
    device_path = os.path.join(sdp, 'device')
    try:
        hctl = os.path.basename(os.path.realpath(device_path))
    except OSError:
        pass
    serial = ''
    for path in (os.path.join(device_path, 'serial'), os.path.join(device_path, 'wwid')):
        try:
            with open(path) as f:
                serial = f.read().strip()
            if serial:
                break
        except IOError:
            pass
    return {'dev': dev, 'ata': ata, 'hctl': hctl, 'serial': serial}

def detect_disks():
    """Map disk slots to /sys/block devices using the upstream ATA mapping strategy."""
    disks = {}
    infos = [block_device_info(p) for p in sorted(glob.glob('/sys/block/sd*'))]
    by_ata = {info['ata']: info['dev'] for info in infos if info['ata']}
    ata_map = cfg.get('ata_map') or model_info.get('ata_map') or [f'ata{i}' for i in range(1, MAX_DISK_LEDS + 1)]
    for idx, ata in enumerate(ata_map, start=1):
        dev = by_ata.get(ata)
        if dev:
            disks[idx] = dev

    if not disks:
        for idx, info in enumerate(infos, start=1):
            disks[idx] = info['dev']
    return disks

def detect_disk_presence(disk_map):
    """Check which disk bays have a physical drive present by reading /sys/block/*/size."""
    presence = {}
    for slot, dev in disk_map.items():
        try:
            with open(f'/sys/block/{dev}/size') as f:
                size_val = int(f.read().strip())
            presence[slot] = size_val > 0
        except (IOError, ValueError):
            presence[slot] = False
    return presence

def detect_net_iface():
    """Find the primary active network interface with carrier."""
    net_dir = '/sys/class/net'
    if not os.path.isdir(net_dir):
        return None
    for iface in sorted(os.listdir(net_dir)):
        if iface == 'lo':
            continue
        carrier_path = f'/sys/class/net/{iface}/carrier'
        try:
            with open(carrier_path) as f:
                if f.read().strip() == '1':
                    return iface
        except IOError:
            pass
    return None

def read_stats(path):
    try:
        with open(path) as f:
            return int(f.read().strip().split()[0])
    except (IOError, ValueError, IndexError):
        return 0

def read_disk_io(path):
    """Return a compact activity counter from Linux /sys/block/*/stat."""
    try:
        with open(path) as f:
            vals = [int(x) for x in f.read().strip().split()]
        # reads completed + writes completed, enough for activity detection
        return vals[0] + vals[4]
    except (IOError, ValueError, IndexError):
        return 0

# ── LED state machine ────────────────────────────────────

class LEDController:
    def __init__(self, led_names):
        self.leds = led_names
        self.modes = {}     # led -> 'off'|'on'|'auto'
        self.activity = {}  # led -> bool (is currently blinking)
        self._disk_map = {}
        self._net_iface = None
        self._prev_net_rx = 0
        self._prev_net_tx = 0
        self._prev_disk_io = {}
        self._disk_presence = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def restore_state(self, hardware_modes=None, apply_hardware=True):
        hardware_modes = hardware_modes or {}
        saved = load_json(STATE_FILE, {})
        for led in self.leds:
            mode = hardware_modes.get(led, saved.get(led, 'off'))
            if mode not in VALID_MODES:
                mode = 'off'
            # Force empty disk bays to 'off'
            if led.startswith('disk'):
                m = re.match(r'disk(\d+)', led)
                if m and not self._disk_presence.get(int(m.group(1)), False):
                    mode = 'off'
            self.modes[led] = mode
            self.activity[led] = False
            if apply_hardware and led not in hardware_modes:
                ok, msg = self._apply(led, mode, activity=False)
                if not ok:
                    print(f'Restore {led} failed: {msg}')
        print(f'Restored state: {self.modes}')

    def set_mode(self, led, mode):
        with self._lock:
            if led not in self.leds:
                return False, f'Invalid LED: {led}'
            ok, msg = self._apply(led, mode, activity=False)
            if not ok:
                return False, msg
            self.modes[led] = mode
            self.activity[led] = False
            self._persist()
            return True, 'OK'

    def _apply(self, led, mode, activity=False):
        """Set hardware LED state based on mode and activity."""
        if led.startswith('disk'):
            m = re.match(r'disk(\d+)', led)
            if m and not self._disk_presence.get(int(m.group(1)), False):
                return True, 'OK'
        if mode == 'off':
            ok, _, err = run(led, '-off')
        elif mode == 'on':
            ok, _, err = run(led, '-on')
        elif mode == 'auto':
            if activity:
                ok, _, err = run(led, '-blink', str(BLINK_ON_MS), str(BLINK_OFF_MS))
            else:
                ok, _, err = run(led, '-off')
        else:
            return False, f'Invalid mode: {mode}'
        return ok, err or 'OK'

    def _persist(self):
        save_json(STATE_FILE, dict(self.modes))

    # ── background monitor ────────────────────────────────

    def start_monitor(self):
        self._disk_map = detect_disks()
        self._disk_presence = detect_disk_presence(self._disk_map)
        self._net_iface = detect_net_iface()
        print(f'Disks: {self._disk_map}')
        print(f'Disk presence: {self._disk_presence}')
        print(f'Network: {self._net_iface or "none"}')

        # Init previous counters
        if self._net_iface:
            base = f'/sys/class/net/{self._net_iface}/statistics'
            self._prev_net_rx = read_stats(f'{base}/rx_bytes')
            self._prev_net_tx = read_stats(f'{base}/tx_bytes')
        for slot, dev in self._disk_map.items():
            self._prev_disk_io[slot] = read_disk_io(f'/sys/block/{dev}/stat')

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop_monitor(self):
        self._stop.set()

    def _monitor_loop(self):
        while not self._stop.wait(MONITOR_INTERVAL):
            try:
                self._check_network()
                self._check_disks()
            except Exception:
                pass

    def _check_network(self):
        led = 'netdev'
        if self.modes.get(led) != 'auto' or not self._net_iface:
            return
        base = f'/sys/class/net/{self._net_iface}/statistics'
        rx = read_stats(f'{base}/rx_bytes')
        tx = read_stats(f'{base}/tx_bytes')
        active = (rx != self._prev_net_rx or tx != self._prev_net_tx)
        self._prev_net_rx = rx
        self._prev_net_tx = tx
        if active != self.activity.get(led):
            self.activity[led] = active
            self._apply(led, 'auto', activity=active)

    def _check_disks(self):
        for slot, dev in list(self._disk_map.items()):
            led = f'disk{slot}'
            if not self._disk_presence.get(slot, False):
                continue
            if self.modes.get(led) != 'auto' or led not in self.leds:
                continue
            try:
                io = read_disk_io(f'/sys/block/{dev}/stat')
            except Exception:
                continue
            prev = self._prev_disk_io.get(slot, 0)
            active = (io != prev)
            self._prev_disk_io[slot] = io
            if active != self.activity.get(led):
                self.activity[led] = active
                ok, msg = self._apply(led, 'auto', activity=active)
                if not ok:
                    print(f'Apply {led} auto failed: {msg}')

    def get_status(self):
        return {
            'modes': dict(self.modes),
            'activity': dict(self.activity),
            'disk_map': {str(k): v for k, v in self._disk_map.items()},
            'disk_presence': {str(k): v for k, v in self._disk_presence.items()},
            'net_iface': self._net_iface,
            'leds': self.leds,
        }


# ── init ──────────────────────────────────────────────────

print(f'FnUGreenLed v1.3  port={PORT}  var={VAR}')

model_info = detect_model()
led_statuses, probe_error = probe_leds()
detected = disk_count_from_leds(led_statuses)
hardware_modes = {led: data['mode'] for led, data in led_statuses.items()}
print(f'Model: {model_info.get("product_name") or model_info.get("name")}')
print(f'Probe: {detected} disk LEDs detected, leds={sorted(led_statuses.keys())}, error={probe_error or "none"}')

# Load or generate auth token
auth_cfg = load_json(AUTH_FILE, {})
if not auth_cfg.get('token'):
    token = secrets.token_hex(16)
    auth_cfg = {'token': token, 'note': 'Include this in X-Auth-Token header for LED control'}
    save_json(AUTH_FILE, auth_cfg)
    print(f'Auth token: {token}')
else:
    print(f'Auth token: {auth_cfg["token"]}')
need_auth = bool(auth_cfg.get('token'))

initialized = os.path.exists(CONFIG_FILE)
default_disk_count = detected or model_info.get('disk_count') or 4
cfg = load_json(CONFIG_FILE, {
    'disk_count': default_disk_count,
    'model': model_info.get('id', 'auto'),
    'model_name': model_info.get('name', 'Unknown'),
    'product_name': model_info.get('product_name', ''),
    'auto_detected': bool(detected or model_info.get('disk_count')),
    'ata_map': model_info.get('ata_map', []),
})
if initialized and detected and not cfg.get('auto_detected'):
    cfg['disk_count'] = detected
    cfg['auto_detected'] = True
    cfg['model'] = model_info.get('id', cfg.get('model', 'auto'))
    cfg['model_name'] = model_info.get('name', cfg.get('model_name', 'Unknown'))
    cfg['product_name'] = model_info.get('product_name', cfg.get('product_name', ''))
    cfg['ata_map'] = model_info.get('ata_map', cfg.get('ata_map', []))
    save_json(CONFIG_FILE, cfg)

disk_count = cfg['disk_count']
led_names = LED_BASE + [f'disk{i}' for i in range(1, disk_count + 1)]
print(f'Active LEDs: {led_names}')

ctrl = LEDController(led_names)
ctrl._disk_map = detect_disks()
ctrl._disk_presence = detect_disk_presence(ctrl._disk_map)
ctrl.restore_state(hardware_modes=hardware_modes, apply_hardware=initialized)
ctrl.start_monitor()

# ── HTML ──────────────────────────────────────────────────

def bay_html(i):
    return f'''<div class="dbay" data-led="disk{i}">
  <div class="bframe">
   <div class="bhdr"><span class="bnum">{i:02d}</span><div class="led sm" id="disk{i}-led"></div></div>
   <div class="bbody"><div class="dicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M2 12h20v6H2zm0-4h20v2H2zm2-6h16c1.1 0 2 .9 2 2v2H2V4c0-1.1.9-2 2-2z"/></svg></div></div>
   <div class="bfooter"><div class="tgl3 sm3" data-led="disk{i}"><div class="trk3"><div class="thm3"></div></div><span class="tlbl3"></span></div></div>
  </div>
 </div>'''

CSS = r'''
:root{--cb1:#3d3d3d;--cb2:#2a2a2a;--cbr:#1a1a1a;--bb1:#353535;--bb2:#252525;--bbr:#1f1f1f;--bis:inset 0 2px 8px rgba(0,0,0,0.5);--lon:#00ff88;--log:0 0 8px #00ff88,0 0 16px #00ff88,0 0 24px rgba(0,255,136,0.5);--loff:#333;--los:inset 0 1px 2px rgba(0,0,0,0.8);--sto:linear-gradient(180deg,#444 0%,#222 100%);--stn:linear-gradient(180deg,#00aa66 0%,#006633 100%);--sth:linear-gradient(180deg,#666 0%,#444 100%);--sthn:linear-gradient(180deg,#00cc66 0%,#009944 100%);--bp:linear-gradient(180deg,#00aa66 0%,#008844 100%);--bs:linear-gradient(180deg,#555 0%,#333 100%);--t1:#e0e0e0;--t2:#888;--t3:#666}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;background:linear-gradient(135deg,#1a1a1a 0%,#0d0d0d 100%);min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}
.nc{width:100%;max-width:640px}
.ncase{background:linear-gradient(145deg,var(--cb1) 0%,var(--cb2) 100%);border-radius:16px;border:2px solid var(--cbr);box-shadow:0 20px 60px rgba(0,0,0,0.6),inset 0 1px 0 rgba(255,255,255,0.08);overflow:hidden}
.hbar{display:flex;align-items:center;padding:20px 24px;background:linear-gradient(180deg,rgba(255,255,255,0.05) 0%,transparent 100%);border-bottom:1px solid rgba(0,0,0,0.3)}
.hicon{width:32px;height:32px;color:var(--lon);filter:drop-shadow(0 0 4px rgba(0,255,136,0.5))}
.htitle{flex:1;font-size:18px;font-weight:600;color:var(--t1);margin-left:12px;letter-spacing:0.5px}
.sdot{width:8px;height:8px;border-radius:50%;background:var(--lon);box-shadow:0 0 8px var(--lon);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
@keyframes autoPulse{0%,100%{opacity:1}50%{opacity:0.3}}
.badge{font-size:11px;color:var(--t3);background:rgba(255,255,255,0.05);padding:3px 8px;border-radius:4px;margin-left:8px;border:1px solid rgba(255,255,255,0.08)}
.ssection{padding:24px;border-bottom:1px solid rgba(0,0,0,0.3)}
.spanel{display:flex;gap:16px;background:linear-gradient(145deg,rgba(0,0,0,0.2) 0%,rgba(0,0,0,0.1) 100%);border-radius:12px;padding:20px;border:1px solid rgba(255,255,255,0.05)}
.sitem{flex:1;display:flex;flex-direction:column;align-items:center;gap:12px;cursor:pointer;user-select:none}
.sheader{display:flex;align-items:center;gap:8px}
.slabel{font-size:14px;color:var(--t2);font-weight:500}
.divider{width:1px;background:linear-gradient(180deg,transparent 0%,rgba(255,255,255,0.1) 50%,transparent 100%)}
.led{width:20px;height:20px;border-radius:50%;background:radial-gradient(circle at 30% 30%,#444 0%,#222 50%,#111 100%);border:2px solid #111;box-shadow:var(--los);transition:all 0.3s ease;position:relative}
.led::after{content:'';position:absolute;top:20%;left:20%;width:30%;height:30%;border-radius:50%;background:rgba(255,255,255,0.1)}
.led.on{background:radial-gradient(circle at 30% 30%,var(--lon) 0%,#00cc66 50%,#008844 100%);box-shadow:var(--log);border-color:#006633}
.led.auto{background:radial-gradient(circle at 30% 30%,var(--lon) 0%,#00cc66 50%,#008844 100%);box-shadow:var(--log);border-color:#006633;animation:autoPulse 1.5s ease-in-out infinite}
.led.sm{width:14px;height:14px}
/* 3-state toggle */
.tgl3{display:flex;flex-direction:column;align-items:center;gap:6px;cursor:pointer;user-select:none}
.trk3{width:62px;height:30px;background:var(--sto);border-radius:15px;border:2px solid #111;position:relative;box-shadow:inset 0 2px 4px rgba(0,0,0,0.5),0 1px 0 rgba(255,255,255,0.1);transition:all 0.3s ease}
.thm3{width:24px;height:24px;background:var(--sth);border-radius:50%;position:absolute;top:1px;left:2px;box-shadow:0 2px 4px rgba(0,0,0,0.4),inset 0 1px 0 rgba(255,255,255,0.2);transition:transform 0.3s cubic-bezier(0.4,0.0,0.2,1)}
.tgl3.st1 .trk3{background:var(--stn)}
.tgl3.st1 .thm3{transform:translateX(15px);background:var(--sthn)}
.tgl3.st2 .trk3{background:linear-gradient(180deg,#0066aa 0%,#003366 100%)}
.tgl3.st2 .thm3{transform:translateX(32px);background:linear-gradient(180deg,#0088cc 0%,#005599 100%)}
.tlbl3{font-size:10px;color:var(--t3);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.tgl3.sm3 .trk3{width:50px;height:24px;border-radius:12px}
.tgl3.sm3 .thm3{width:18px;height:18px}
.tgl3.sm3.st1 .thm3{transform:translateX(12px)}
.tgl3.sm3.st2 .thm3{transform:translateX(26px)}
.dsection{padding:24px}
.dtitle{font-size:13px;color:var(--t3);text-transform:uppercase;letter-spacing:2px;margin-bottom:16px;padding-left:8px}
.dgrid{display:grid;gap:12px}
.dbay{cursor:pointer}
.bframe{background:linear-gradient(145deg,var(--bb1) 0%,var(--bb2) 100%);border-radius:8px;border:1px solid var(--bbr);box-shadow:var(--bis),0 2px 4px rgba(0,0,0,0.3);padding:12px 8px;display:flex;flex-direction:column;align-items:center;gap:10px;transition:all 0.2s ease}
.dbay:hover .bframe{box-shadow:var(--bis),0 4px 8px rgba(0,0,0,0.4);transform:translateY(-2px)}
.dbay:active .bframe{transform:translateY(0);box-shadow:inset 0 3px 8px rgba(0,0,0,0.6),0 1px 2px rgba(0,0,0,0.3)}
.bhdr{display:flex;align-items:center;justify-content:space-between;width:100%;padding:0 4px}
.bnum{font-size:14px;font-weight:700;color:var(--t3);font-family:"SF Mono",Monaco,monospace}
.bbody{flex:1;display:flex;align-items:center;justify-content:center;padding:8px 0}
.dicon{width:36px;height:36px;color:var(--t3);opacity:0.5;transition:all 0.3s ease}
.dbay.active .dicon{color:var(--lon);opacity:0.8;filter:drop-shadow(0 0 4px rgba(0,255,136,0.3))}
.bfooter{padding-top:4px}
.fbar{display:flex;gap:12px;padding:20px 24px;background:rgba(0,0,0,0.2);border-top:1px solid rgba(0,0,0,0.3)}
.abtn{flex:1;display:flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;background:var(--bp);border:none;border-radius:8px;color:white;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 4px 8px rgba(0,0,0,0.3),inset 0 1px 0 rgba(255,255,255,0.2);transition:all 0.2s ease}
.abtn:hover{transform:translateY(-2px);box-shadow:0 6px 12px rgba(0,0,0,0.4),inset 0 1px 0 rgba(255,255,255,0.2)}
.abtn:active{transform:translateY(0);box-shadow:0 2px 4px rgba(0,0,0,0.3),inset 0 2px 4px rgba(0,0,0,0.3)}
.abtn.s{background:var(--bs)}
.abtn.auto{background:linear-gradient(180deg,#0088cc 0%,#005077 100%)}
.abtn.danger{background:linear-gradient(180deg,#8a3a3a 0%,#542323 100%)}
.bicon{width:18px;height:18px;opacity:0.9}
/* legend */
.legend{display:flex;gap:16px;padding:8px 24px 16px;justify-content:center}
.leg-item{display:flex;align-items:center;gap:4px;font-size:10px;color:var(--t3)}
.leg-dot{width:8px;height:8px;border-radius:50%}
.leg-dot.off{background:var(--loff);border:1px solid #555}
.leg-dot.on{background:var(--lon);box-shadow:0 0 4px var(--lon)}
.leg-dot.auto{background:#0088cc;box-shadow:0 0 4px #0088cc}
.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%) translateY(100px);background:linear-gradient(145deg,#3a3a3a 0%,#2a2a2a 100%);color:var(--t1);padding:12px 24px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);box-shadow:0 8px 24px rgba(0,0,0,0.5);font-size:14px;opacity:0;transition:all 0.3s ease;z-index:1000}
.toast.show{transform:translateX(-50%) translateY(0);opacity:1}
.toast.ok{border-left:3px solid var(--lon)}
.toast.err{border-left:3px solid #ff4444}
.init-panel{padding:28px 24px 24px;border-top:1px solid rgba(255,255,255,0.04)}
.init-copy{color:var(--t2);font-size:13px;line-height:1.7;margin-bottom:20px}
.init-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}
.choice{padding:14px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.08);background:linear-gradient(145deg,#303030,#242424);color:var(--t1);font-size:13px;font-weight:600;cursor:pointer;box-shadow:var(--bis);transition:all .2s ease}
.choice:hover,.choice.active{border-color:#00aa66;box-shadow:var(--bis),0 0 0 1px rgba(0,255,136,.25),0 0 18px rgba(0,255,136,.16)}
.init-actions{display:flex;gap:12px}
.init-actions .abtn{flex:1}
@media(max-width:480px){.dgrid{grid-template-columns:repeat(2,1fr)!important}.spanel{flex-direction:column}.divider{width:100%;height:1px;background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,0.1) 50%,transparent 100%)}}
'''

JS = r'''
(function(){
var LEDS=__LEDS_JSON__;
var modes=__INIT_MODES__;
var MODE_LABEL=['关闭','常亮','自动'];
function api(m,p,b){var o={method:m,headers:{'Content-Type':'application/json'}};if(b)o.body=JSON.stringify(b);return fetch(p,o).then(function(r){return r.json()}).catch(function(e){return{success:false,message:e.message}})}
function updateUI(led,mode,activity){modes[led]=mode;var el=document.getElementById(led+'-led');if(el){el.classList.remove('on','auto');if(mode==='on')el.classList.add('on')}
var tgl=document.querySelector('.tgl3[data-led="'+led+'"]');if(tgl){tgl.classList.remove('st0','st1','st2');var labels=['关闭','常亮','自动'];var states=['st0','st1','st2'];var idx=['off','on','auto'].indexOf(mode);if(idx>=0){tgl.classList.add(states[idx]);tgl.querySelector('.tlbl3').textContent=labels[idx]}}
var bay=document.querySelector('.dbay[data-led="'+led+'"]');if(bay){bay.classList.toggle('active',mode!=='off')}
var statusDot=document.getElementById('system-status');if(statusDot&&mode!=='off'){statusDot.style.animationName=(mode==='auto')?'autoPulse':'pulse'}}
function toast(m,t){t=t||'ok';var e=document.getElementById('toast');e.textContent=m;e.className='toast show '+t;setTimeout(function(){e.classList.remove('show')},2500)}
function lname(l){var m=l.match(/^disk(\d+)$/);if(m)return'磁盘'+m[1]+'灯';if(l==='power')return'电源灯';if(l==='netdev')return'网络灯';return l}
function cycleMode(led){var order=['off','on','auto'];var idx=order.indexOf(modes[led]||'off');var next=order[(idx+1)%3];api('POST','/api/control',{led:led,action:next}).then(function(r){if(r.success){updateUI(led,next);toast(lname(led)+' → '+MODE_LABEL[(idx+1)%3])}else toast('操作失败: '+r.message,'err')})}
function allMode(mode){var label=MODE_LABEL[['off','on','auto'].indexOf(mode)];toast('正在将所有指示灯设为: '+label);api('POST','/api/all/'+mode,{}).then(function(r){if(r.success){LEDS.forEach(function(led){updateUI(led,mode)});toast('所有指示灯已设为: '+label)}else toast('操作失败: '+r.message,'err')})}
function resetConfig(){if(!confirm('重置会清空本地配置和保存的指示灯模式，并返回初始化页面。继续吗？'))return;api('POST','/api/reset',{}).then(function(r){if(r.success){toast('配置已重置');setTimeout(function(){location.href='/'},500)}else toast('重置失败: '+r.message,'err')})}
function pollStatus(){api('GET','/api/status').then(function(r){if(r.success&&r.activity){for(var led in r.activity){if(modes[led]==='auto'){var el=document.getElementById(led+'-led');if(el){el.classList.remove('auto');if(r.activity[led])el.classList.add('on');else el.classList.remove('on')}}}}})}
function init(){
document.querySelectorAll('.tgl3').forEach(function(t){t.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();var l=t.dataset.led;if(l&&LEDS.indexOf(l)!==-1)cycleMode(l)})});
document.querySelectorAll('.dbay').forEach(function(b){b.addEventListener('click',function(e){if(e.target.closest('.tgl3'))return;var l=b.dataset.led;if(l&&LEDS.indexOf(l)!==-1)cycleMode(l)})});
document.querySelectorAll('.sitem').forEach(function(i){i.addEventListener('click',function(e){if(e.target.closest('.tgl3'))return;var l=i.dataset.led;if(l&&LEDS.indexOf(l)!==-1)cycleMode(l)})});
document.getElementById('btn-all-on').addEventListener('click',function(){allMode('on')});
document.getElementById('btn-all-off').addEventListener('click',function(){allMode('off')});
var autoBtn=document.getElementById('btn-all-auto');if(autoBtn)autoBtn.addEventListener('click',function(){allMode('auto')});
var resetBtn=document.getElementById('btn-reset');if(resetBtn)resetBtn.addEventListener('click',resetConfig);
LEDS.forEach(function(led){updateUI(led,modes[led]||'off')});
setInterval(pollStatus,800)
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init()
})()
'''

INIT_JS = r'''
(function(){
var selected=__INIT_DISK_COUNT__;
function api(m,p,b){var o={method:m,headers:{'Content-Type':'application/json'}};if(b)o.body=JSON.stringify(b);return fetch(p,o).then(function(r){return r.json()}).catch(function(e){return{success:false,message:e.message}})}
function mark(){document.querySelectorAll('.choice').forEach(function(btn){btn.classList.toggle('active',parseInt(btn.dataset.count,10)===selected)})}
function toast(m,t){t=t||'ok';var e=document.getElementById('toast');e.textContent=m;e.className='toast show '+t;setTimeout(function(){e.classList.remove('show')},2500)}
function save(){api('POST','/api/config',{disk_count:selected,model:'manual'}).then(function(r){if(r.success){location.href='/'}else toast('初始化失败: '+r.message,'err')})}
function init(){document.querySelectorAll('.choice').forEach(function(btn){btn.addEventListener('click',function(){selected=parseInt(btn.dataset.count,10);mark()})});var saveBtn=document.getElementById('btn-init-save');saveBtn.addEventListener('click',save);mark()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init()
})()
'''

HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>指示灯控制</title>
<style>{css}</style>
</head>
<body>
<div class="nc">
 <div class="ncase">
  <div class="hbar">
   <div class="hicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></div>
   <h1 class="htitle">指示灯控制</h1>
   <span class="badge">{disk_count}盘位</span>
   <div class="hstatus"><span class="sdot" id="system-status"></span></div>
  </div>
  <div class="legend">
   <div class="leg-item"><span class="leg-dot off"></span> 关闭</div>
   <div class="leg-item"><span class="leg-dot on"></span> 常亮</div>
   <div class="leg-item"><span class="leg-dot auto"></span> 自动</div>
  </div>
  <div class="ssection">
   <div class="spanel">
    <div class="sitem" data-led="power">
     <div class="sheader"><span class="slabel">电源</span><div class="led" id="power-led"></div></div>
     <div class="tgl3" data-led="power"><div class="trk3"><div class="thm3"></div></div><span class="tlbl3"></span></div>
    </div>
    <div class="divider"></div>
    <div class="sitem" data-led="netdev">
     <div class="sheader"><span class="slabel">网络</span><div class="led" id="netdev-led"></div></div>
     <div class="tgl3" data-led="netdev"><div class="trk3"><div class="thm3"></div></div><span class="tlbl3"></span></div>
    </div>
   </div>
  </div>
  <div class="dsection">
   <div class="dtitle">磁盘指示灯</div>
   <div class="dgrid" style="grid-template-columns:repeat({disk_count},1fr);">
    {disk_bays}
   </div>
  </div>
  <div class="fbar">
   <button class="abtn" id="btn-all-on"><span class="bicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg></span>全部常亮</button>
   <button class="abtn auto" id="btn-all-auto"><span class="bicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 6V3L8 7l4 4V8c2.21 0 4 1.79 4 4 0 .68-.17 1.32-.47 1.88l1.46 1.46C17.63 14.38 18 13.23 18 12c0-3.31-2.69-6-6-6zm-4 6c0-.68.17-1.32.47-1.88L7.01 8.66C6.37 9.62 6 10.77 6 12c0 3.31 2.69 6 6 6v3l4-4-4-4v3c-2.21 0-4-1.79-4-4z"/></svg></span>全部自动</button>
   <button class="abtn s" id="btn-all-off"><span class="bicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg></span>全部关闭</button>
  </div>
  <div class="fbar">
   <button class="abtn danger" id="btn-reset"><span class="bicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 5V2L7 7l5 5V9c2.76 0 5 2.24 5 5 0 1.04-.32 2-.86 2.8l1.46 1.46C18.48 17.08 19 15.6 19 14c0-3.87-3.13-7-7-7zm-5.6.74C5.52 6.92 5 8.4 5 10c0 3.87 3.13 7 7 7v3l5-5-5-5v3c-2.76 0-5-2.24-5-5 0-1.04.32-2 .86-2.8L6.4 5.74z"/></svg></span>重置配置</button>
  </div>
 </div>
</div>
<div class="toast" id="toast"></div>
<script>{js}</script>
</body>
</html>'''

INIT_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>指示灯控制 - 初始化</title>
<style>{css}</style>
</head>
<body>
<div class="nc">
 <div class="ncase">
  <div class="hbar">
   <div class="hicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15H9v-2h2v2zm0-4H9V7h2v6zm4 4h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg></div>
   <h1 class="htitle">初始化配置</h1>
   <span class="badge">探测 {detected} 盘位</span>
  </div>
  <div class="init-panel">
   <div class="init-copy">请选择当前设备的盘位数量。保存后会创建新的本地配置，并进入指示灯控制页面。</div>
   <div class="init-grid">
    <button class="choice" data-count="2">2 盘位</button>
    <button class="choice" data-count="4">4 盘位</button>
    <button class="choice" data-count="6">6 盘位</button>
    <button class="choice" data-count="8">8 盘位</button>
   </div>
   <div class="init-actions">
    <button class="abtn" id="btn-init-save"><span class="bicon"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg></span>保存并进入</button>
   </div>
  </div>
 </div>
</div>
<div class="toast" id="toast"></div>
<script>{js}</script>
</body>
</html>'''


def build_page():
    bays = '\n'.join(bay_html(i) for i in range(1, disk_count + 1))
    js = (JS
        .replace('__LEDS_JSON__', json.dumps(led_names))
        .replace('__INIT_MODES__', json.dumps(ctrl.modes)))
    return HTML.format(
        css=CSS,
        js=js,
        disk_count=disk_count,
        disk_bays=bays
    )

def build_init_page():
    cfg_count = cfg.get('disk_count', 4)
    suggested = detected if detected in (2, 4, 6, 8) else (cfg_count if cfg_count in (2, 4, 6, 8) else 4)
    js = INIT_JS.replace('__INIT_DISK_COUNT__', str(suggested))
    return INIT_HTML.format(css=CSS, js=js, detected=detected or '未识别')

# ── HTTP handler ───────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self._html(200, build_page() if initialized else build_init_page())
        elif self.path == '/api/status':
            self._json(200, {
                'success': True,
                'initialized': initialized,
                'model': model_info,
                'hardware': led_statuses,
                **ctrl.get_status(),
            })
        elif self.path == '/api/config':
            self._json(200, {
                'success': True,
                'initialized': initialized,
                'config': cfg,
                'detected': detected,
                'model': model_info,
                'hardware_leds': sorted(led_statuses.keys()),
                'probe_error': probe_error,
            })
        else:
            self._json(404, {})

    def do_POST(self):
        if need_auth and not check_auth(self.headers):
            return self._json(401, {'success': False, 'message': 'Unauthorized'})
        body = self._body()
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return self._json(400, {'success': False, 'message': 'Invalid JSON'})

        if self.path == '/api/control':
            self._control(data)
        elif self.path in ('/api/all/off', '/api/all/on', '/api/all/auto'):
            mode = self.path.rsplit('/', 1)[-1]
            self._all(mode)
        elif self.path == '/api/config':
            self._set_config(data)
        elif self.path == '/api/reset':
            self._reset_config()
        else:
            self._json(404, {})

    def _control(self, data):
        led = data.get('led', '')
        mode = data.get('action', '')  # 'off'|'on'|'auto'
        if led not in led_names:
            return self._json(400, {'success': False, 'message': f'无效指示灯: {led}'})
        if mode not in VALID_MODES:
            return self._json(400, {'success': False, 'message': f'无效模式: {mode}'})
        ok, message = ctrl.set_mode(led, mode)
        if ok:
            labels = {'off': '关闭', 'on': '常亮', 'auto': '自动'}
            self._json(200, {'success': True, 'message': f'{led} → {labels[mode]}'})
        else:
            self._json(500, {'success': False, 'message': message or '设置失败'})

    def _all(self, mode):
        errors = []
        for led in led_names:
            ok, message = ctrl.set_mode(led, mode)
            if not ok:
                errors.append(f'{led}: {message}')
        if errors:
            return self._json(500, {'success': False, 'message': '; '.join(errors)})
        labels = {'off': '关闭', 'on': '常亮', 'auto': '自动'}
        self._json(200, {'success': True, 'message': f'所有指示灯 → {labels[mode]}'})

    def _set_config(self, data):
        global disk_count, led_names, ctrl, initialized
        n = data.get('disk_count', 0)
        if isinstance(n, int) and 1 <= n <= MAX_DISK_LEDS:
            cfg['disk_count'] = n
            cfg['model'] = data.get('model', model_info.get('id', 'manual'))
            cfg['model_name'] = model_info.get('name', cfg.get('model_name', 'Unknown'))
            cfg['product_name'] = model_info.get('product_name', cfg.get('product_name', ''))
            cfg['auto_detected'] = bool(detected)
            cfg['ata_map'] = model_info.get('ata_map', cfg.get('ata_map', []))
            save_json(CONFIG_FILE, cfg)
            initialized = True
            disk_count = n
            led_names = LED_BASE + [f'disk{i}' for i in range(1, disk_count + 1)]
            ctrl.stop_monitor()
            ctrl = LEDController(led_names)
            ctrl.restore_state(hardware_modes=hardware_modes)
            ctrl.start_monitor()
            self._json(200, {'success': True, 'message': f'已切换到 {disk_count} 盘位', 'disk_count': disk_count, 'leds': led_names})
        else:
            self._json(400, {'success': False, 'message': f'无效盘位数量: {n}'})

    def _reset_config(self):
        global cfg, disk_count, led_names, ctrl, initialized, model_info, led_statuses, detected, hardware_modes, probe_error
        errors = []
        for path in (CONFIG_FILE, STATE_FILE):
            err = remove_file(path)
            if err:
                errors.append(f'{os.path.basename(path)}: {err}')
        if errors:
            return self._json(500, {'success': False, 'message': '; '.join(errors)})

        model_info = detect_model()
        led_statuses, probe_error = probe_leds()
        detected = disk_count_from_leds(led_statuses)
        hardware_modes = {led: data['mode'] for led, data in led_statuses.items()}
        initialized = False
        cfg = {
            'disk_count': detected or model_info.get('disk_count') or 4,
            'model': model_info.get('id', 'auto'),
            'model_name': model_info.get('name', 'Unknown'),
            'product_name': model_info.get('product_name', ''),
            'auto_detected': bool(detected or model_info.get('disk_count')),
            'ata_map': model_info.get('ata_map', []),
        }
        disk_count = cfg['disk_count']
        led_names = LED_BASE + [f'disk{i}' for i in range(1, disk_count + 1)]
        ctrl.stop_monitor()
        ctrl = LEDController(led_names)
        ctrl.restore_state(hardware_modes=hardware_modes, apply_hardware=False)
        ctrl.start_monitor()
        self._json(200, {'success': True, 'message': '配置已重置', 'initialized': initialized})

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length) if length else ''

    def _json(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _html(self, status, content):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'Listening on 0.0.0.0:{PORT}')
    server.serve_forever()
