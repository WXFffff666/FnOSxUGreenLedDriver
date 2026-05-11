# FnUGreenLed

UGREEN DXP4800 系列 NAS 的 LED 指示灯控制应用，基于 fnOS（飞牛）应用框架开发。

## 功能

- 控制 DXP4800 NAS 前面板的 6 个 LED 指示灯：电源、网络、4 个磁盘槽位
- 每个 LED 独立开关
- 一键全部开启 / 全部关闭
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
# 生成 FnUGreenLed-1.0.0.x86_64.fpk
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
appcenter-cli install-fpk FnUGreenLed-1.0.0.x86_64.fpk
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
{ "led": "power|netdev|disk1|disk2|disk3|disk4", "action": "on|off" }

// Response (success)
{ "success": true, "message": "power 已开启" }

// Response (error)
{ "success": false, "message": "无法访问 I2C 设备..." }
```

## 技术架构

```
fnOS 桌面 → 浏览器打开 http://127.0.0.1:8080
                ↓
         main.py (Python HTTP Server)
         GET  /            → HTML 页面（内嵌 CSS/JS）
         POST /api/control → JSON API
                ↓ subprocess
         ugreen_leds_cli (static x86_64)
                ↓ I2C
         硬件 LED 控制器 (地址 0x3a)
```

## 注意事项

- 仅支持 x86_64 架构（UGREEN DXP4800 系列）
- 需要 NAS 内核加载 `i2c-dev` 模块
- 应用需要 root 权限或 I2C 组权限才能访问硬件
- LED 状态无法读取（驱动只支持写入），UI 初始状态始终显示为关闭
