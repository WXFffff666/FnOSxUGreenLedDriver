#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FnUGreenLed — LED Controller HTTP Server
Serves UI and API for controlling 6 LEDs on UGREEN DXP4800 NAS.
"""

import os
import json
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

VALID_LEDS = ['power', 'netdev', 'disk1', 'disk2', 'disk3', 'disk4']
VALID_ACTIONS = ['on', 'off']
# Try bundled binary first, fall back to system-installed path
_BUNDLED_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ugreen_leds_cli')
CLI_PATH = _BUNDLED_CLI if os.path.exists(_BUNDLED_CLI) else '/usr/local/bin/ugreen_leds_cli'
PORT = int(os.environ.get('TRIM_SERVICE_PORT', 8080))


def run_cli(led, action):
    try:
        cmd = [CLI_PATH, led, f'-{action}']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return True, 'OK'
        err = result.stderr.strip()
        # Translate common I2C errors to actionable Chinese messages
        if 'fail to open the I2C device' in err:
            return False, '无法访问 I2C 设备。请确保：1) i2c-dev 内核模块已加载 (sudo modprobe i2c-dev)  2) 应用有 root 权限或 I2C 组访问权限'
        if 'Permission denied' in err or 'permission' in err.lower():
            return False, '权限不足，无法访问 I2C 设备。请检查应用是否以 root 身份运行。'
        return False, err
    except FileNotFoundError:
        return False, f'LED 驱动未找到: {CLI_PATH}'
    except Exception as e:
        return False, str(e)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/control':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                led = data.get('led', '')
                action = data.get('action', '')
                if led not in VALID_LEDS:
                    result = {'success': False, 'message': f'无效的指示灯: {led}'}
                elif action not in VALID_ACTIONS:
                    result = {'success': False, 'message': f'无效的操作: {action}'}
                else:
                    success, message = run_cli(led, action)
                    result = {'success': success, 'message': message if not success else f'{led} 已{action == "on" and "开启" or "关闭"}'}
            except Exception as e:
                result = {'success': False, 'message': str(e)}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress default stderr logging


HTML_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>指示灯控制</title>
<style>
:root {
    --case-bg-start: #3d3d3d;
    --case-bg-end: #2a2a2a;
    --case-border: #1a1a1a;
    --bay-bg-start: #353535;
    --bay-bg-end: #252525;
    --bay-border: #1f1f1f;
    --bay-inner-shadow: inset 0 2px 8px rgba(0,0,0,0.5);
    --led-on: #00ff88;
    --led-on-glow: 0 0 8px #00ff88, 0 0 16px #00ff88, 0 0 24px rgba(0,255,136,0.5);
    --led-off: #333;
    --led-off-shadow: inset 0 1px 2px rgba(0,0,0,0.8);
    --switch-track-off: linear-gradient(180deg, #444 0%, #222 100%);
    --switch-track-on: linear-gradient(180deg, #00aa66 0%, #006633 100%);
    --switch-thumb: linear-gradient(180deg, #666 0%, #444 100%);
    --switch-thumb-on: linear-gradient(180deg, #00cc66 0%, #009944 100%);
    --btn-primary: linear-gradient(180deg, #00aa66 0%, #008844 100%);
    --btn-secondary: linear-gradient(180deg, #555 0%, #333 100%);
    --text-primary: #e0e0e0;
    --text-secondary: #888;
    --text-muted: #666;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
}
.nas-container { width:100%; max-width:600px; }
.nas-case {
    background: linear-gradient(145deg, var(--case-bg-start) 0%, var(--case-bg-end) 100%);
    border-radius: 16px;
    border: 2px solid var(--case-border);
    box-shadow: 0 20px 60px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.08);
    overflow: hidden;
}
.header-bar {
    display: flex;
    align-items: center;
    padding: 20px 24px;
    background: linear-gradient(180deg, rgba(255,255,255,0.05) 0%, transparent 100%);
    border-bottom: 1px solid rgba(0,0,0,0.3);
}
.header-icon {
    width: 32px; height: 32px;
    color: var(--led-on);
    filter: drop-shadow(0 0 4px rgba(0,255,136,0.5));
}
.header-title {
    flex: 1;
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
    margin-left: 12px;
    letter-spacing: 0.5px;
}
.status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--led-on);
    box-shadow: 0 0 8px var(--led-on);
    animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
.status-section {
    padding: 24px;
    border-bottom: 1px solid rgba(0,0,0,0.3);
}
.status-panel {
    display: flex;
    gap: 16px;
    background: linear-gradient(145deg, rgba(0,0,0,0.2) 0%, rgba(0,0,0,0.1) 100%);
    border-radius: 12px;
    padding: 20px;
    border: 1px solid rgba(255,255,255,0.05);
}
.status-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    user-select: none;
}
.status-header {
    display: flex;
    align-items: center;
    gap: 8px;
}
.status-label {
    font-size: 14px;
    color: var(--text-secondary);
    font-weight: 500;
}
.divider {
    width: 1px;
    background: linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.1) 50%, transparent 100%);
}
.led-indicator {
    width: 20px; height: 20px;
    border-radius: 50%;
    background: radial-gradient(circle at 30% 30%, #444 0%, #222 50%, #111 100%);
    border: 2px solid #111;
    box-shadow: var(--led-off-shadow);
    transition: all 0.3s ease;
    position: relative;
}
.led-indicator::after {
    content: '';
    position: absolute;
    top: 20%; left: 20%;
    width: 30%; height: 30%;
    border-radius: 50%;
    background: rgba(255,255,255,0.1);
}
.led-indicator.on {
    background: radial-gradient(circle at 30% 30%, var(--led-on) 0%, #00cc66 50%, #008844 100%);
    box-shadow: var(--led-on-glow);
    border-color: #006633;
}
.led-indicator.small {
    width: 14px; height: 14px;
}
.toggle-switch {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    user-select: none;
}
.switch-track {
    width: 56px; height: 28px;
    background: var(--switch-track-off);
    border-radius: 14px;
    border: 2px solid #111;
    position: relative;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.1);
    transition: all 0.3s ease;
}
.switch-thumb {
    width: 24px; height: 24px;
    background: var(--switch-thumb);
    border-radius: 50%;
    position: absolute;
    top: 0; left: 0;
    box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.2);
    transition: transform 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
}
.toggle-switch.on .switch-track { background: var(--switch-track-on); }
.toggle-switch.on .switch-thumb {
    transform: translateX(28px);
    background: var(--switch-thumb-on);
}
.switch-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1px;
}
.toggle-switch.small .switch-track { width:44px; height:22px; border-radius:11px; }
.toggle-switch.small .switch-thumb { width:18px; height:18px; }
.toggle-switch.small.on .switch-thumb { transform: translateX(22px); }
.disk-section { padding: 24px; }
.section-title {
    font-size: 13px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 16px;
    padding-left: 8px;
}
.disk-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.disk-bay { cursor: pointer; }
.bay-frame {
    background: linear-gradient(145deg, var(--bay-bg-start) 0%, var(--bay-bg-end) 100%);
    border-radius: 8px;
    border: 1px solid var(--bay-border);
    box-shadow: var(--bay-inner-shadow), 0 2px 4px rgba(0,0,0,0.3);
    padding: 12px 8px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    transition: all 0.2s ease;
}
.disk-bay:hover .bay-frame {
    box-shadow: var(--bay-inner-shadow), 0 4px 8px rgba(0,0,0,0.4);
    transform: translateY(-2px);
}
.disk-bay:active .bay-frame {
    transform: translateY(0);
    box-shadow: inset 0 3px 8px rgba(0,0,0,0.6), 0 1px 2px rgba(0,0,0,0.3);
}
.bay-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 0 4px;
}
.bay-number {
    font-size: 14px;
    font-weight: 700;
    color: var(--text-muted);
    font-family: "SF Mono", Monaco, monospace;
}
.bay-body {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 8px 0;
}
.disk-icon {
    width: 36px; height: 36px;
    color: var(--text-muted);
    opacity: 0.5;
    transition: all 0.3s ease;
}
.disk-bay.active .disk-icon {
    color: var(--led-on);
    opacity: 0.8;
    filter: drop-shadow(0 0 4px rgba(0,255,136,0.3));
}
.bay-footer { padding-top: 4px; }
.footer-bar {
    display: flex;
    gap: 12px;
    padding: 20px 24px;
    background: rgba(0,0,0,0.2);
    border-top: 1px solid rgba(0,0,0,0.3);
}
.action-btn {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 14px 20px;
    background: var(--btn-primary);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 4px 8px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.2);
    transition: all 0.2s ease;
}
.action-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 12px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.2);
}
.action-btn:active {
    transform: translateY(0);
    box-shadow: 0 2px 4px rgba(0,0,0,0.3), inset 0 2px 4px rgba(0,0,0,0.3);
}
.action-btn.secondary { background: var(--btn-secondary); }
.btn-icon { width:18px; height:18px; opacity:0.9; }
.toast-container {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    background: linear-gradient(145deg, #3a3a3a 0%, #2a2a2a 100%);
    color: var(--text-primary);
    padding: 12px 24px;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.1);
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    font-size: 14px;
    opacity: 0;
    transition: all 0.3s ease;
    z-index: 1000;
}
.toast-container.show { transform: translateX(-50%) translateY(0); opacity: 1; }
.toast-container.success { border-left: 3px solid var(--led-on); }
.toast-container.error { border-left: 3px solid #ff4444; }
@media (max-width: 480px) {
    .disk-grid { grid-template-columns: repeat(2, 1fr); }
    .status-panel { flex-direction: column; }
    .divider {
        width: 100%; height: 1px;
        background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.1) 50%, transparent 100%);
    }
}
</style>
</head>
<body>
<div class="nas-container">
    <div class="nas-case">
        <div class="header-bar">
            <div class="header-icon">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                </svg>
            </div>
            <h1 class="header-title">指示灯控制</h1>
            <div class="header-status"><span class="status-dot" id="system-status"></span></div>
        </div>
        <div class="status-section">
            <div class="status-panel">
                <div class="status-item" data-led="power">
                    <div class="status-header">
                        <span class="status-label">电源</span>
                        <div class="led-indicator" id="power-led"></div>
                    </div>
                    <div class="toggle-switch" data-led="power">
                        <div class="switch-track"><div class="switch-thumb"></div></div>
                        <span class="switch-label">开关</span>
                    </div>
                </div>
                <div class="divider"></div>
                <div class="status-item" data-led="netdev">
                    <div class="status-header">
                        <span class="status-label">网络</span>
                        <div class="led-indicator" id="netdev-led"></div>
                    </div>
                    <div class="toggle-switch" data-led="netdev">
                        <div class="switch-track"><div class="switch-thumb"></div></div>
                        <span class="switch-label">开关</span>
                    </div>
                </div>
            </div>
        </div>
        <div class="disk-section">
            <div class="section-title">磁盘指示灯</div>
            <div class="disk-grid">
                <div class="disk-bay" data-led="disk1">
                    <div class="bay-frame">
                        <div class="bay-header">
                            <span class="bay-number">01</span>
                            <div class="led-indicator small" id="disk1-led"></div>
                        </div>
                        <div class="bay-body">
                            <div class="disk-icon">
                                <svg viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M2 12h20v6H2zm0-4h20v2H2zm2-6h16c1.1 0 2 .9 2 2v2H2V4c0-1.1.9-2 2-2z"/>
                                </svg>
                            </div>
                        </div>
                        <div class="bay-footer">
                            <div class="toggle-switch small" data-led="disk1">
                                <div class="switch-track"><div class="switch-thumb"></div></div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="disk-bay" data-led="disk2">
                    <div class="bay-frame">
                        <div class="bay-header">
                            <span class="bay-number">02</span>
                            <div class="led-indicator small" id="disk2-led"></div>
                        </div>
                        <div class="bay-body">
                            <div class="disk-icon">
                                <svg viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M2 12h20v6H2zm0-4h20v2H2zm2-6h16c1.1 0 2 .9 2 2v2H2V4c0-1.1.9-2 2-2z"/>
                                </svg>
                            </div>
                        </div>
                        <div class="bay-footer">
                            <div class="toggle-switch small" data-led="disk2">
                                <div class="switch-track"><div class="switch-thumb"></div></div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="disk-bay" data-led="disk3">
                    <div class="bay-frame">
                        <div class="bay-header">
                            <span class="bay-number">03</span>
                            <div class="led-indicator small" id="disk3-led"></div>
                        </div>
                        <div class="bay-body">
                            <div class="disk-icon">
                                <svg viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M2 12h20v6H2zm0-4h20v2H2zm2-6h16c1.1 0 2 .9 2 2v2H2V4c0-1.1.9-2 2-2z"/>
                                </svg>
                            </div>
                        </div>
                        <div class="bay-footer">
                            <div class="toggle-switch small" data-led="disk3">
                                <div class="switch-track"><div class="switch-thumb"></div></div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="disk-bay" data-led="disk4">
                    <div class="bay-frame">
                        <div class="bay-header">
                            <span class="bay-number">04</span>
                            <div class="led-indicator small" id="disk4-led"></div>
                        </div>
                        <div class="bay-body">
                            <div class="disk-icon">
                                <svg viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M2 12h20v6H2zm0-4h20v2H2zm2-6h16c1.1 0 2 .9 2 2v2H2V4c0-1.1.9-2 2-2z"/>
                                </svg>
                            </div>
                        </div>
                        <div class="bay-footer">
                            <div class="toggle-switch small" data-led="disk4">
                                <div class="switch-track"><div class="switch-thumb"></div></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="footer-bar">
            <button class="action-btn" id="btn-all-on">
                <span class="btn-icon">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                    </svg>
                </span>
                全部开启
            </button>
            <button class="action-btn secondary" id="btn-all-off">
                <span class="btn-icon">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                    </svg>
                </span>
                全部关闭
            </button>
        </div>
    </div>
</div>
<div class="toast-container" id="toast"></div>
<script>
(function() {
    'use strict';
    var ledState = { power: false, netdev: false, disk1: false, disk2: false, disk3: false, disk4: false };
    var VALID_LEDS = ['power', 'netdev', 'disk1', 'disk2', 'disk3', 'disk4'];
    function controlLED(led, action) {
        return fetch('/api/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ led: led, action: action })
        }).then(function(r) { return r.json(); })
          .catch(function(e) { return { success: false, message: e.message }; });
    }
    function updateLEDIndicator(led, isOn) {
        var indicator = document.getElementById(led + '-led');
        if (indicator) {
            if (isOn) indicator.classList.add('on');
            else indicator.classList.remove('on');
        }
    }
    function updateSwitchState(led, isOn) {
        var switches = document.querySelectorAll('[data-led="' + led + '"].toggle-switch');
        switches.forEach(function(el) {
            if (isOn) el.classList.add('on');
            else el.classList.remove('on');
        });
        var diskBay = document.querySelector('.disk-bay[data-led="' + led + '"]');
        if (diskBay) {
            if (isOn) diskBay.classList.add('active');
            else diskBay.classList.remove('active');
        }
    }
    function updateLEDState(led, isOn) {
        ledState[led] = isOn;
        updateLEDIndicator(led, isOn);
        updateSwitchState(led, isOn);
    }
    function showToast(message, type) {
        type = type || 'success';
        var toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = 'toast-container ' + type + ' show';
        setTimeout(function() { toast.classList.remove('show'); }, 2500);
    }
    function getLEDName(led) {
        var names = { power: '电源灯', netdev: '网络灯', disk1: '磁盘1灯', disk2: '磁盘2灯', disk3: '磁盘3灯', disk4: '磁盘4灯' };
        return names[led] || led;
    }
    function handleToggle(led) {
        var currentState = ledState[led];
        var newAction = currentState ? 'off' : 'on';
        controlLED(led, newAction).then(function(result) {
            if (result.success) {
                updateLEDState(led, !currentState);
                showToast(getLEDName(led) + '已' + (newAction === 'on' ? '开启' : '关闭'));
            } else {
                showToast('操作失败: ' + result.message, 'error');
            }
        });
    }
    function handleAllOn() {
        showToast('正在开启所有指示灯...');
        var promises = VALID_LEDS.map(function(led) {
            if (!ledState[led]) {
                return controlLED(led, 'on').then(function(result) {
                    if (result.success) updateLEDState(led, true);
                    return result;
                });
            }
            return Promise.resolve({ success: true });
        });
        Promise.all(promises).then(function() { showToast('所有指示灯已开启'); });
    }
    function handleAllOff() {
        showToast('正在关闭所有指示灯...');
        var promises = VALID_LEDS.map(function(led) {
            if (ledState[led]) {
                return controlLED(led, 'off').then(function(result) {
                    if (result.success) updateLEDState(led, false);
                    return result;
                });
            }
            return Promise.resolve({ success: true });
        });
        Promise.all(promises).then(function() { showToast('所有指示灯已关闭'); });
    }
    function init() {
        document.querySelectorAll('.toggle-switch').forEach(function(sw) {
            sw.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                var led = sw.dataset.led;
                if (led && VALID_LEDS.indexOf(led) !== -1) handleToggle(led);
            });
        });
        document.querySelectorAll('.disk-bay').forEach(function(bay) {
            bay.addEventListener('click', function(e) {
                if (e.target.closest('.toggle-switch')) return;
                var led = bay.dataset.led;
                if (led && VALID_LEDS.indexOf(led) !== -1) handleToggle(led);
            });
        });
        document.querySelectorAll('.status-item').forEach(function(item) {
            item.addEventListener('click', function(e) {
                if (e.target.closest('.toggle-switch')) return;
                var led = item.dataset.led;
                if (led && VALID_LEDS.indexOf(led) !== -1) handleToggle(led);
            });
        });
        document.getElementById('btn-all-on').addEventListener('click', handleAllOn);
        document.getElementById('btn-all-off').addEventListener('click', handleAllOff);
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
</script>
</body>
</html>'''


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
