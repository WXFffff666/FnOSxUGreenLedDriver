# FnUGreenLed

UGREEN NAS 的 LED 指示灯控制应用，基于 fnOS（飞牛）应用框架开发。

> **🔱 Fork 自 [Mikawawawa/FnOSxUGreenLedDriver](https://github.com/Mikawawawa/FnOSxUGreenLedDriver)**（原始作者：Mikawawawa）  
> 当前维护者：[WXFffff666](https://github.com/WXFffff666)  
> 版本：v1.3.0 — 新增鉴权、智能盘位检测、卸载 LED 恢复

## 适配机型

| 型号 | 盘位数 | LED 数 | I2C 地址 | 验证状态 | 说明 |
|------|--------|--------|----------|----------|------|
| **DXP4800 Plus** | 4 | 6 | 0x3a (bus 1) | ✅ 已测试 | 前面板带显示屏，LED 控制与 DXP4800 完全一致 |
| DXP4800 | 4 | 6 | 0x3a (bus 1) | ✅ 已测试 | 原始适配机型 |
| DX4600 Pro | 4 | 6 | 0x3a (bus 1) | ✅ 社区报告 | — |
| DX4700+ | 4 | 6 | 0x3a (bus 1) | ✅ 社区报告 | — |
| DXP2800 | 2 | 4 | 0x3a (bus 1) | ⚠️ 待验证 | — |
| DXP6800 Pro | 6 | 8 | 0x3a (bus 1) | ⚠️ 待验证 | ATA 映射特殊顺序 |
| DXP8800 Plus | 8 | 10 | 0x3a (bus 1) | ⚠️ 待验证 | — |
| DXP480T | 4 | 1 | **0x26** | ❌ 待适配 | 仅电源 LED，不同协议 |

### DXP4800 Plus 适配详情

- **DMI 型号探测**：双前缀匹配 (`DXP4800Plus` + `DXP4800 Plus`)，覆盖 DMI 产品名的两种可能格式
- **DMI 产品名确认为** `DXP4800 Plus`（来源：[linux-hardware.org 探针](https://linux-hardware.org/?probe=b4d3ebcb90)）
- **盘位 ATA 映射**：`ata1→disk1, ata2→disk2, ata3→disk3, ata4→disk4`（与 DXP4800 一致，上游 [miskcoo/ugreen_leds_controller](https://github.com/miskcoo/ugreen_leds_controller) 已确认）
- **I2C 协议**：bus 1, 地址 0x3a（与所有 DXP 系列相同），参考 [Kerryliu TrueNAS 指南](https://gist.github.com/Kerryliu/c380bb6b3b69be5671105fc23e19b7e8)（125 stars, DXP4800 Plus 用户实测通过）
- **LED 驱动**：从上游最新源码 Docker 交叉编译（Alpine musl-g++ 静态链接 x86_64）

## 功能

- 控制 NAS 前面板 LED：电源、网络、磁盘槽位
- 每个 LED 支持三种模式：关闭、常亮、自动
- 一键全部常亮 / 全部自动 / 全部关闭
- **智能盘位检测**：自动识别已插入硬盘的槽位，空槽位自动熄灯
- **访问鉴权**：API 写入操作需 Token 验证，仅允许持有者控制
- **卸载安全**：移除应用时自动关闭所有 LED，恢复硬件默认状态
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
# 生成 FnUGreenLed-1.3.0.x86_64.fpk
```

## 安装与调试

### 在 NAS 上安装

> ⚠️ **安装安全性说明**：本应用安装过程**完全无破坏性**：
> - 仅加载 `i2c-dev` 内核模块（已加载则跳过）
> - 创建专用用户 `ledcontroller` / 用户组 `ledcontroller`（不影响现有用户）
> - 在 `/usr/local/bin/` 创建 `ugreen_leds_cli` 符号链接
> - 所有数据写入应用专属目录 `/var/apps/FnUGreenLed/var/`，**不触碰系统文件**
> - 卸载时 fnOS 自动清理上述所有内容

```bash
# 1. 从 GitHub Release 下载 .fpk 文件
#    https://github.com/WXFffff666/FnOSxUGreenLedDriver/releases

# 2. SSH 到 NAS，启用第三方安装
appcenter-cli manual-install enable

# 3. 安装 .fpk
appcenter-cli install-fpk /path/to/FnUGreenLed.fpk

# 4. 安装完成后，在 fnOS 桌面打开「指示灯控制」即可
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
- DXP4800 Plus 的 DMI 产品名确认为 `DXP4800 Plus`，代码中已添加双前缀匹配兼容

## 致谢

- 原始项目 [Mikawawawa/FnOSxUGreenLedDriver](https://github.com/Mikawawawa/FnOSxUGreenLedDriver) — 应用框架与 UI 设计
- LED 驱动 [miskcoo/ugreen_leds_controller](https://github.com/miskcoo/ugreen_leds_controller) — I2C 协议与 CLI 实现
- DXP4800 Plus 适配验证参考 [Kerryliu 的 TrueNAS 指南](https://gist.github.com/Kerryliu/c380bb6b3b69be5671105fc23e19b7e8)
