# 🚀 Portable WebDAV Client (便携 WebDAV 客户端)

![软件主界面](assets/screenshot.png)

一个基于 Python + Tkinter 开发的轻量级、便携式 WebDAV 客户端。支持快速连接 WebDAV 服务器（如 123 云盘、坚果云、AList 等），提供直观的可视化界面进行文件浏览、下载与上传。

## ✨ 核心特性

- **🧳 绿色免安装**：提供打包好的单文件可执行程序，不写注册表、不留系统垃圾，放进 U 盘插上就能用。
- **🎈 极致轻量**：纯 Python 编写，运行资源占用极低，老电脑也能流畅运行。
- **🖥️ 现代 UI**：采用 `ttk` 扁平化主题，支持 Treeview 多列文件列表、Emoji 图标与 Windows 高 DPI。
- **🖱️ 便捷交互**：
  - 双击进入文件夹 / 提示并下载文件。
  - 右键菜单（下载、上传、复制名称、复制完整路径、刷新）。
  - 路径历史记录、返回上级、绝对路径一键跳转。
  - 点击表头按名称 / 类型 / 大小排序，文件夹始终置顶。
- **📥 智能下载**：后台线程下载，实时显示进度与网速；先写 `.part` 临时文件再原子替换，取消或失败不会破坏本地同名旧文件。
- **📤 稳定上传**：流式上传并显示真实进度与网速，单文件上限 2 GB。
- **🧵 不卡界面**：目录加载、下载、上传均在后台线程执行，并通过请求令牌避免快速切换目录时旧结果覆盖新目录。
- **🔒 隐私安全**：账号密码仅在内存中流转，不生成任何本地配置文件，用完即关。

## ⌨️ 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `F5` | 刷新当前目录 |
| `Enter` | 打开选中项 |
| `Backspace` | 返回上级目录 |
| `Ctrl + C` | 复制选中文件名 |
| `Ctrl + Shift + C` | 复制选中文件完整路径 |

## 📦 如何使用（普通用户）

如果你不想配置 Python 环境，可以直接下载打包好的便携版可执行文件：

1. 前往本项目的 [Releases 页面](https://github.com/jiu-zui-90817/Portable-WebDAV-Client/releases)。
2. 下载最新的可执行文件（PyInstaller 或 Nuitka 版本均可）。
3. 双击直接运行，无需安装。

## 🛠️ 如何开发 / 运行源代码

要求 Python 3.9+。

**1. 克隆项目**

```bash
git clone https://github.com/jiu-zui-90817/Portable-WebDAV-Client.git
cd Portable-WebDAV-Client
```

**2. 安装依赖**

```bash
python -m pip install -r requirements.txt
```

Linux 还需要系统自带的 tkinter（Debian/Ubuntu）：

```bash
sudo apt-get install -y python3-tk
```

**3. 启动**

```bash
python portable_webdav_client_Pro.py
```

**4. 运行测试**

```bash
python -m unittest discover -s tests -t . -v
```

## 📦 自行打包

**PyInstaller**

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name Portable_WebDAV_Client ^
  --icon=webdav.ico --add-data "webdav.ico;." portable_webdav_client_Pro.py
```

**Nuitka**

```bash
pip install nuitka
python -m nuitka --onefile --enable-plugin=tk-inter ^
  --windows-disable-console --windows-icon-from-ico=webdav.ico ^
  --include-data-file=webdav.ico=webdav.ico ^
  portable_webdav_client_Pro.py
```

> Linux / macOS 下把 `^` 换成 `\`，并把 `;` 换成 `:` 即可。

## 📁 项目结构

```text
Portable-WebDAV-Client/
├── portable_webdav_client_Pro.py   # 主程序（单文件实现）
├── requirements.txt                # Python 依赖
├── tests/                          # 不依赖窗口的纯逻辑单元测试
├── assets/screenshot.png           # README 截图
├── webdav.ico                      # 程序图标
└── .github/workflows/build.yml     # 多平台自动构建与 Release
```

## ❓ 常见问题

- **连接 123 云盘 / AList 失败？** 先确认 WebDAV 地址、用户名与密码（部分服务使用单独的 WebDAV 应用密码）。
- **上传按钮不可用？** 连接成功且目录加载完成后才会启用；国内网盘的真实写权限在上传时由服务端校验。
- **Linux 启动报 `No module named tkinter`？** 安装 `python3-tk` 后重试。
- **打包后窗口没有图标？** 确认打包时通过 `--add-data`（PyInstaller）或 `--include-data-file`（Nuitka）带上了 `webdav.ico`。

## 🔐 安全说明

用户名和密码只保存在当前进程内存中，程序不会写入配置文件、注册表或日志。关闭窗口后即释放。

## 📄 License

本项目基于 [LICENSE](LICENSE) 开源。
