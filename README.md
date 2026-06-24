# FnUGreenLed

UGREEN NAS 的 LED 指示灯控制应用，基于 fnOS（飞牛）应用框架开发。

## 功能

- 控制 NAS 前面板 LED：电源、网络、磁盘槽位
- 每个 LED 支持三种模式：关闭、常亮、自动
- 一键全部常亮 / 全部自动 / 全部关闭
- LED 模式持久化到应用 var 目录，服务重启后自动恢复
- 自动探测可用磁盘 LED 数量，并支持手动切换 1-8 盘位
- 通过 `ugreen_leds_cli all -status` 读取可用 LED 和当前硬件状态
- 通过 DMI 产品名辅助识别 UGREEN 型号并套用盘位映射
- 适用于 DXP2800/DXP4800/DXP4800 Plus/DXP6800/DXP8800 等系列
- 自动模式下根据网络流量和磁盘 I/O 活动切换指示状态
- 支持重置配置，清空本地配置后重新进入初始化页面
- 拟物化 UI，模拟 DXP4800 金属外壳外观

## 项目结构

```
src/
├── app/server/main.py          # Python HTTP 服务（内嵌 UI + API）
├── app/server/ugreen_leds_cli  # LED 驱动（静态编译 x86_64）
├── app/ui/config               # 桌面入口配置
├── app/ui/images/              # 桌面图标
├── cmd/                        # 生命周期脚本
├── config/                     # 权限与资源声明
├── manifest                    # 应用元数据
└── wizard/                     # 安装向导（空）
```

## 依赖

| 依赖 | 说明 |
|------|------|
| Python 3 | HTTP 服务运行环境 |
| i2c-dev | Linux 内核 I2C 模块（NAS 上需加载） |
| [ugreen_leds_cli](https://github.com/miskcoo/ugreen_leds_controller) | LED 硬件驱动（已静态编译打包） |

## 构建

### 前置条件

- macOS / Linux / Windows
- [Docker](https://www.docker.com/)（用于交叉编译 LED 驱动）
- fnpack CLI 工具

### 编译 LED 驱动

[驱动项目](https://github.com/miskcoo/ugreen_leds_controller)使用了社区成熟的项目

```bash
docker run --platform linux/amd64 --rm \
  -v "$PWD/src/app/server":/output \
  -w /build alpine:latest sh -c '
    apk add --no-cache git g++ make linux-headers &&
    git clone --depth 1 https://github.com/miskcoo/ugreen_leds_controller.git &&
    cd ugreen_leds_controller/cli && make &&
    cp ugreen_leds_cli /output/'
```

### 打包

```bash
fnpack build --directory src
# 生成 FnUGreenLed-1.1.0.x86_64.fpk
```

## 安装与调试

### 在 NAS 上安装

```bash
# SSH 到 NAS，启用第三方安装
appcenter-cli manual-install enable

# 从本地目录安装（开发调试推荐）
cd /path/to/project/src
appcenter-cli install-local

# 或从 fpk 文件安装
appcenter-cli install-fpk FnUGreenLed-1.1.0.x86_64.fpk
```

### NAS 环境检查

```bash
# 检查 I2C 设备
ls /dev/i2c-*

# 加载 I2C 内核模块
sudo modprobe i2c-dev

# 检测 LED 控制器（地址 0x3a）
sudo i2cdetect -y 1

# 查看应用日志
cat /var/apps/FnUGreenLed/var/info.log
```

### 手动测试 LED 驱动

```bash
/usr/local/bin/ugreen_leds_cli power -on
/usr/local/bin/ugreen_leds_cli power -off
/usr/local/bin/ugreen_leds_cli disk1 -on
```

## API

### `POST /api/control`

```json
// Request
{ "led": "power|netdev|disk1|disk2|...", "action": "off|on|auto" }

// Response (success)
{ "success": true, "message": "power → 常亮" }

// Response (error)
{ "success": false, "message": "无法访问 I2C 设备..." }
```

### `GET /api/status`

返回当前 LED 模式、活动状态、磁盘映射和网络接口。

### `POST /api/all/off|on|auto`

批量设置所有已启用 LED 的模式。

### `GET /api/config` / `POST /api/config`

读取或设置当前盘位数量：

```json
{ "disk_count": 6, "model": "manual" }
```

`GET /api/config` 同时返回型号探测结果、硬件 LED 列表和探测错误信息，便于排查 I2C/权限/驱动问题。

### `POST /api/reset`

删除 `device_config.json` 与 `led_state.json`，应用回到未初始化状态。下一次访问 `/` 会显示初始化页面。

## 技术架构

```
fnOS 桌面 → 浏览器打开 http://127.0.0.1:19580
                ↓
         main.py (Python HTTP Server)
         GET  /            → HTML 页面（内嵌 CSS/JS）
         /api/*             → JSON API
                ↓ subprocess
         ugreen_leds_cli (static x86_64)
                ↓ I2C
         硬件 LED 控制器 (地址 0x3a)
```

## 注意事项

- 仅支持 x86_64 架构
- 需要 NAS 内核加载 `i2c-dev` 模块
- 应用需要 root 权限或 I2C 组权限才能访问硬件
- `auto` 模式依赖 Linux `/sys/class/net` 和 `/sys/block` 统计信息
- CLI 仍是硬件写入工具，真实 LED 状态以应用持久化状态和自动检测结果为准
- 已测试 DXP4800 Plus，LED 控制功能与 DXP4800 完全一致
