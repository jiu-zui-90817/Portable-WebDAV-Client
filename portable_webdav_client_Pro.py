"""便携 WebDAV 客户端 Pro.

基于 Tkinter + webdavclient3 的单文件桌面客户端，支持 WebDAV 目录浏览、下载与上传。
"""

import os
import posixpath
import re
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import Menu, filedialog, messagebox, simpledialog, ttk

from webdav3.client import Client
from webdav3.urn import Urn

APP_NAME = "便携 WebDAV 客户端 Pro"
APP_VERSION = "1.6.0"
DEFAULT_URL = "https://webdav.123pan.cn/webdav"
REQUEST_TIMEOUT = 60          # 秒。避免服务器无响应时后台线程永久挂起
MAX_UPLOAD_MB = 2048          # WebDAV PUT 的实用上限，同时防止误传超大文件
MAX_CACHE_ENTRIES = 64        # 目录缓存上限，避免长时间浏览后内存持续增长
CHUNK_SIZE = 256 * 1024
HIDE_ALIST_WEBDAV_FOLDER = True   # 隐藏 AList 根目录下冗余的 webdav 虚拟目录
APP_ICON = "webdav.ico"

_DEFAULT_HEADINGS = {"name": "文件名称", "type": "类型", "size": "大小"}


def resource_path(relative_path):
    """兼容源码运行与 PyInstaller/Nuitka 单文件打包的资源路径。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def enable_high_dpi():
    """在 Windows 上开启 DPI 感知，避免高分屏下界面发虚。"""
    if os.name != "nt":
        return
    try:
        import ctypes
    except Exception:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class WebDAVApp:
    def __init__(self, root):
        self.root = root

        # 运行状态
        self.client = None
        self.current_path = "/"
        self.history = []                  # 浏览历史
        self.cache = {}                    # 路径 -> 文件列表缓存
        self.current_has_permission = True # 国内网盘默认放行，真实权限由上传异常兜底
        self.is_downloading = False
        self.is_uploading = False
        self.cancel_flag = False
        self._loading = False
        self._load_token = 0               # 防止快速切换目录时旧响应覆盖新目录
        self._current_items = []           # (名称, 是否目录, 大小, 远端路径)
        self._row_paths = {}               # Treeview iid -> 远端路径
        self._sort_column = "name"
        self._sort_reverse = False
        self._headings = dict(_DEFAULT_HEADINGS)

        try:
            self._ui_scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self._ui_scale = 1.0

        self.root.title(f"{APP_NAME} V{APP_VERSION}")
        self.root.minsize(int(760 * self._ui_scale), int(520 * self._ui_scale))
        self.center_window(int(850 * self._ui_scale), int(650 * self._ui_scale))
        self._set_window_icon()

        # 启用更现代的内置主题
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        # 自定义 Treeview 样式
        style.configure("Treeview", rowheight=int(28 * self._ui_scale),
                        font=("Microsoft YaHei", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei", 10, "bold"),
                        background="#e1e1e1")
        style.map("Treeview", background=[("selected", "#4361ee")])

        self.create_widgets()
        self.create_context_menu()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- 界面搭建 ----------
    def _set_window_icon(self):
        try:
            self.root.iconbitmap(resource_path(APP_ICON))
        except Exception:
            pass  # Linux 或图标缺失时忽略，不影响启动

    def create_widgets(self):
        # ========== 顶部：连接配置区域 ==========
        config_frame = ttk.LabelFrame(self.root, text=" 连接配置 ", padding=(15, 10))
        config_frame.grid(row=0, column=0, padx=15, pady=10, sticky="ew")
        self.root.grid_columnconfigure(0, weight=1)

        ttk.Label(config_frame, text="WebDAV 地址:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.url_entry = ttk.Entry(config_frame, width=50)
        self.url_entry.insert(0, DEFAULT_URL)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, sticky="we")

        ttk.Label(config_frame, text="用户名:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        default_user = "WebdavUser"  # 请替换为真实用户名
        self.real_username = default_user
        self.placeholder_username = self.mask_username(default_user)

        self.user_entry = ttk.Entry(config_frame, width=50, foreground="gray")
        self.user_entry.insert(0, self.placeholder_username)
        self.user_entry.grid(row=1, column=1, padx=5, pady=5, sticky="we")
        self.user_entry.bind("<FocusIn>", self.on_user_focus_in)
        self.user_entry.bind("<FocusOut>", self.on_user_focus_out)

        ttk.Label(config_frame, text="密码:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.pwd_entry = ttk.Entry(config_frame, width=50, show="*")
        self.pwd_entry.grid(row=2, column=1, padx=5, pady=5, sticky="we")

        self.connect_btn = ttk.Button(config_frame, text="🔌 连接服务器", command=self.connect, width=15)
        self.connect_btn.grid(row=0, column=2, rowspan=3, padx=15, pady=5, sticky="ns")
        config_frame.grid_columnconfigure(1, weight=1)

        self.url_entry.bind("<Return>", lambda _e: self.connect())
        self.pwd_entry.bind("<Return>", lambda _e: self.connect())

        # ========== 工具栏区域 ==========
        toolbar_frame = ttk.Frame(self.root)
        toolbar_frame.grid(row=1, column=0, padx=15, pady=5, sticky="ew")

        self.up_btn = ttk.Button(toolbar_frame, text="⬆️ 返回上级", command=self.go_up, state=tk.DISABLED)
        self.up_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.refresh_btn = ttk.Button(toolbar_frame, text="🔄 刷新", command=self.refresh, state=tk.DISABLED)
        self.refresh_btn.pack(side=tk.LEFT, padx=5)

        self.jump_btn = ttk.Button(toolbar_frame, text="🚀 跳转路径", command=self.jump_to_path, state=tk.DISABLED)
        self.jump_btn.pack(side=tk.LEFT, padx=5)

        self.download_btn = ttk.Button(toolbar_frame, text="📥 下载选中项", command=self.download_selected, state=tk.DISABLED)
        self.download_btn.pack(side=tk.LEFT, padx=5)

        self.upload_btn = ttk.Button(toolbar_frame, text="📤 上传文件", command=self.upload_file, state=tk.DISABLED)
        self.upload_btn.pack(side=tk.LEFT, padx=5)

        # ========== 路径显示 ==========
        path_frame = ttk.Frame(self.root)
        path_frame.grid(row=2, column=0, padx=15, pady=(0, 5), sticky="ew")
        self.path_label = ttk.Label(path_frame, text="当前路径: /", font=("Microsoft YaHei", 9, "bold"),
                                    foreground="#4361ee")
        self.path_label.pack(side=tk.LEFT)

        # ========== 文件列表 (Treeview) ==========
        list_frame = ttk.Frame(self.root)
        list_frame.grid(row=3, column=0, padx=15, pady=5, sticky="nsew")
        self.root.grid_rowconfigure(3, weight=1)

        columns = ("name", "type", "size")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        for column, label in _DEFAULT_HEADINGS.items():
            anchor = tk.W if column == "name" else (tk.CENTER if column == "type" else tk.E)
            self.tree.heading(column, text=label, anchor=anchor,
                              command=lambda c=column: self.sort_by(c))

        self.tree.column("name", width=int(500 * self._ui_scale), anchor=tk.W)
        self.tree.column("type", width=int(100 * self._ui_scale), anchor=tk.CENTER)
        self.tree.column("size", width=int(120 * self._ui_scale), anchor=tk.E)

        y_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<Double-1>", self.on_item_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu)

        # ========== 底部：进度条与状态栏 ==========
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.grid(row=4, column=0, padx=15, pady=10, sticky="ew")

        self.status = ttk.Label(bottom_frame, text="就绪", foreground="gray")
        self.status.pack(side=tk.LEFT)

        self.progress_label = ttk.Label(bottom_frame, text="", font=("Courier", 9))
        self.progress_label.pack(side=tk.RIGHT, padx=5)

        self.progress = ttk.Progressbar(bottom_frame, orient=tk.HORIZONTAL, length=300, mode="determinate")
        self.progress.pack(side=tk.RIGHT, padx=10)

    def create_context_menu(self):
        self.context_menu = Menu(self.root, tearoff=0, font=("Microsoft YaHei", 9))
        self.context_menu.add_command(label="📥 下载选中文件", command=self.download_selected)
        self.context_menu.add_command(label="📤 上传文件到当前目录", command=self.upload_file)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📋 复制文件名称", command=self.copy_filename)
        self.context_menu.add_command(label="🔗 复制完整路径", command=self.copy_remote_path)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔄 刷新", command=self.refresh)

    def _bind_shortcuts(self):
        self.root.bind("<F5>", lambda _e: self.refresh())
        self.tree.bind("<Return>", lambda _e: self._activate_selected())
        self.tree.bind("<BackSpace>", lambda _e: self.go_up())
        self.tree.bind("<Control-c>", lambda _e: self.copy_filename())
        self.tree.bind("<Control-C>", lambda _e: self.copy_remote_path())

    # ---------- 工具函数 ----------
    def center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(width, int(screen_width * 0.95))
        height = min(height, int(screen_height * 0.9))
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def mask_username(self, username):
        if len(username) == 11 and username.isdigit():
            return username[:3] + "****" + username[-4:]
        return username

    def on_user_focus_in(self, event=None):
        current = self.user_entry.get()
        if current == self.placeholder_username:
            self.user_entry.delete(0, tk.END)
            self.user_entry.config(foreground="black")

    def on_user_focus_out(self, event=None):
        current = self.user_entry.get().strip()
        if not current:
            self.user_entry.insert(0, self.placeholder_username)
            self.user_entry.config(foreground="gray")

    def set_status(self, text, color="black"):
        self.status.config(text=text, foreground=color)
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass

    @staticmethod
    def format_size(size_in_bytes):
        """把字节数格式化成人可读的大小；0 字节显示 0 B 而不是 -。"""
        if size_in_bytes is None or size_in_bytes == "":
            return "-"
        try:
            size = float(size_in_bytes)
        except (TypeError, ValueError):
            return "-"
        if size < 0:
            return "-"
        if size < 1024:
            return f"{size:.0f} B"
        for unit in ("KB", "MB", "GB", "TB"):
            size /= 1024.0
            if size < 1024 or unit == "TB":
                precision = 2 if unit in ("GB", "TB") else 1
                return f"{size:.{precision}f} {unit}"
        return f"{size:.2f} TB"

    @staticmethod
    def format_speed(bytes_per_second):
        if not bytes_per_second or bytes_per_second <= 0:
            return "0 KB/s"
        if bytes_per_second >= 1024 * 1024:
            return f"{bytes_per_second / (1024 * 1024):.2f} MB/s"
        return f"{bytes_per_second / 1024:.1f} KB/s"

    @staticmethod
    def _normalize_remote(path):
        if not path:
            return "/"
        path = str(path).replace("\\", "/")
        path = re.sub(r"/+", "/", path)
        if not path.startswith("/"):
            path = "/" + path
        path = path.rstrip("/")
        return path or "/"

    def _join_remote(self, name):
        name = str(name).strip("/")
        return self._normalize_remote(posixpath.join(self.current_path or "/", name))

    @staticmethod
    def _parent_remote(path):
        path = WebDAVApp._normalize_remote(path)
        if path == "/":
            return "/"
        return posixpath.dirname(path) or "/"

    @staticmethod
    def _remove_file(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # ---------- 缓存 ----------
    def _cache_put(self, path, files):
        if path in self.cache:
            self.cache.pop(path)
        self.cache[path] = files
        while len(self.cache) > MAX_CACHE_ENTRIES:
            self.cache.pop(next(iter(self.cache)))

    # ---------- 权限兜底策略 ----------
    def check_upload_permission(self, path):
        """探测当前目录写权限。

        123 云盘、阿里云盘等国内网盘网关会拦截 OPTIONS 请求（返回 401），
        提前嗅探会误判为只读。因此这里默认放行，真正的权限问题由上传时的
        try/except 捕获并弹出错误提示兜底。
        """
        return True

    # ---------- 右键菜单 ----------
    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def copy_filename(self):
        selection = self.tree.selection()
        if selection:
            base_name = self.tree.item(selection[0], "text")
            self.root.clipboard_clear()
            self.root.clipboard_append(base_name)
            self.set_status(f"已复制: {base_name}", "green")

    def copy_remote_path(self):
        selection = self.tree.selection()
        if selection:
            remote = self._row_paths.get(selection[0], "")
            if remote:
                self.root.clipboard_clear()
                self.root.clipboard_append(remote)
                self.set_status(f"已复制路径: {remote}", "green")

    # ---------- 路径跳转 ----------
    def jump_to_path(self):
        if not self.client or self._loading:
            return
        path = simpledialog.askstring("跳转路径", "请输入目标路径（如 /app/Windows）：",
                                      initialvalue=self.current_path)
        if not path:
            return
        path = self._normalize_remote(path.strip())
        self.set_status(f"正在验证路径 {path} ...", "blue")
        threading.Thread(target=self._jump_to_path_worker, args=(path,), daemon=True).start()

    def _jump_to_path_worker(self, path):
        client = self.client
        if client is None:
            return
        try:
            if not client.check(path):
                self.root.after(0, self._jump_fail, path, "服务器上找不到该路径或文件，请检查拼写。")
                return

            if client.is_dir(path):
                files = client.list(path, get_info=True)
                self.root.after(0, self._jump_success, path, files)
            else:
                self.root.after(0, self._jump_is_file, path)
        except Exception as exc:
            self.root.after(0, self._jump_fail, path, str(exc))

    def _jump_is_file(self, path):
        base_name = posixpath.basename(path)
        if messagebox.askyesno("发现文件", f"目标路径是一个文件，是否直接下载？\n\n{base_name}"):
            self.download_file(base_name, full_path=path)

    def _jump_success(self, path, files):
        self.history.clear()
        self._cache_put(path, files)
        self._navigate_to(path, add_history=False)
        self.set_status(f"已跳转到 {path}", "green")

    def _jump_fail(self, path, error):
        self.set_status("路径无效", "red")
        messagebox.showerror("错误", f"无法访问路径 {path}\n{error}")

    # ---------- 连接 ----------
    def connect(self):
        url = self.url_entry.get().strip()
        input_user = self.user_entry.get().strip()
        user = self.real_username if input_user == self.placeholder_username else input_user
        pwd = self.pwd_entry.get()  # 密码不做 strip，避免吃掉合法空格

        if not url or not user or not pwd:
            messagebox.showwarning("提示", "请填写完整的地址、用户名和密码")
            return

        self.real_username = user
        self.connect_btn.config(state=tk.DISABLED, text="连接中...")
        self.set_status("正在连接服务器...", "blue")
        threading.Thread(target=self._do_connect, args=(url, user, pwd), daemon=True).start()

    def _do_connect(self, url, user, pwd):
        try:
            client = Client({
                "webdav_hostname": url,
                "webdav_login": user,
                "webdav_password": pwd,
                "webdav_timeout": REQUEST_TIMEOUT,
            })
            files = client.list("/", get_info=True)
        except Exception as exc:
            self.root.after(0, self._connect_failed, exc)
            return

        # 只有列表成功后才对外发布 client，避免"连接失败但 client 已被赋值"的中间态
        self.root.after(0, self._connect_succeeded, client, user, files)

    def _connect_succeeded(self, client, user, files):
        self.client = client
        self.real_username = user
        self.cache.clear()
        self.current_path = "/"
        self.history.clear()
        self._cache_put("/", files)
        self.tree.delete(*self.tree.get_children())
        self._current_items = []
        self._row_paths.clear()
        self._update_file_list(files)
        self.connect_btn.config(state=tk.NORMAL, text="🔌 重新连接")
        self._set_nav_state()
        self.set_status("连接成功", "green")

    def _connect_failed(self, exc):
        self.connect_btn.config(state=tk.NORMAL, text="🔌 连接服务器")
        self.set_status("连接失败", "red")
        messagebox.showerror("连接失败", str(exc))

    # ---------- 目录加载与列表渲染 ----------
    def _navigate_to(self, path, add_history=True, force=False):
        path = self._normalize_remote(path)
        if add_history and path != self.current_path:
            self.history.append(self.current_path)
        self.current_path = path
        self.path_label.config(text=f"当前路径: {path}")
        self.tree.delete(*self.tree.get_children())
        self._current_items = []
        self._row_paths.clear()
        self._load_folder(path, force=force)

    def _load_folder(self, path, force=False):
        """加载目录。缓存命中时同步渲染，否则交给后台线程，避免阻塞 UI。"""
        client = self.client
        if client is None:
            return
        path = self._normalize_remote(path)
        if not force and path in self.cache:
            self._loading = False
            self._apply_loaded(path, self.cache[path])
            return

        self._loading = True
        self._load_token += 1
        token = self._load_token
        self._set_nav_state()
        self.set_status(f"正在加载 {path} ...", "blue")
        threading.Thread(target=self._load_folder_worker,
                         args=(client, path, token), daemon=True).start()

    def _load_folder_worker(self, client, path, token):
        try:
            files = client.list(path, get_info=True)
        except Exception as exc:
            self.root.after(0, self._load_failed, path, token, str(exc))
            return
        self.root.after(0, self._load_finished, path, token, files)

    def _load_finished(self, path, token, files):
        if token != self._load_token or path != self.current_path:
            return  # 用户已经切到别的目录，丢弃过期响应
        self._cache_put(path, files)
        self._loading = False
        self._apply_loaded(path, files)

    def _load_failed(self, path, token, error):
        if token != self._load_token or path != self.current_path:
            return
        self._loading = False
        self._set_nav_state()
        self.set_status("加载失败", "red")
        messagebox.showerror("加载失败", error)

    def _apply_loaded(self, path, files):
        if path != self.current_path:
            return
        self._update_file_list(files)
        if self._current_items:
            self.set_status("列表加载完成", "green")

    def _build_items(self, files):
        items = []
        seen = set()
        if not files:
            return items

        for entry in files:
            name = ""
            is_dir = False
            size = 0

            if isinstance(entry, str):
                raw = entry.strip()
                if not raw:
                    continue
                is_dir = raw.endswith("/")
                raw = raw.rstrip("/")
                name = posixpath.basename(raw)
            elif isinstance(entry, dict):
                raw = str(entry.get("path") or entry.get("name") or "").rstrip("/")
                name = posixpath.basename(raw) or str(entry.get("name") or "")
                is_dir = bool(entry.get("isdir"))
                size = entry.get("size") or 0
            else:
                continue

            if not name or name in (".", ".."):
                continue
            # webdavclient3 的 list() 已过滤当前目录自身，这里不再按 basename 猜测，
            # 否则会误伤与父目录同名的合法子目录（例如 /foo/foo）。
            if HIDE_ALIST_WEBDAV_FOLDER and self.current_path == "/" and is_dir and name == "webdav":
                continue
            if name in seen:
                continue
            seen.add(name)
            items.append((name, is_dir, size, self._join_remote(name)))

        return items

    def _sorted_items(self):
        directories = [item for item in self._current_items if item[1]]
        files = [item for item in self._current_items if not item[1]]

        if self._sort_column == "size":
            def key(item):
                try:
                    return float(item[2] or 0)
                except (TypeError, ValueError):
                    return 0.0
        else:
            def key(item):
                return (item[0].casefold(), item[0])

        directories.sort(key=key, reverse=self._sort_reverse)
        files.sort(key=key, reverse=self._sort_reverse)
        return directories + files

    def _update_headings(self):
        for column, label in self._headings.items():
            suffix = ""
            if column == self._sort_column:
                suffix = " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(column, text=label + suffix)

    def sort_by(self, column):
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._render_items()

    def _render_items(self):
        self.tree.delete(*self.tree.get_children())
        self._row_paths.clear()

        for name, is_dir, size_raw, remote in self._sorted_items():
            icon = "📁" if is_dir else "📄"
            type_str = "文件夹" if is_dir else "文件"
            size_str = "-" if is_dir else self.format_size(size_raw)
            iid = self.tree.insert(
                "", tk.END, text=name,
                values=(f"{icon}  {name}", type_str, size_str),
                tags=("dir" if is_dir else "file",),
            )
            self._row_paths[iid] = remote

        self._update_headings()

    def _update_file_list(self, files):
        self._current_items = self._build_items(files)
        self._render_items()
        self.path_label.config(text=f"当前路径: {self.current_path}")
        self._set_nav_state()
        if not self._current_items:
            self.set_status("目录为空", "gray")

    def _set_nav_state(self):
        connected = self.client is not None
        busy = self._loading or self.is_downloading or self.is_uploading

        self.up_btn.config(state=tk.NORMAL if connected and not busy and self.current_path != "/" else tk.DISABLED)
        self.refresh_btn.config(state=tk.NORMAL if connected and not busy else tk.DISABLED)
        self.jump_btn.config(state=tk.NORMAL if connected and not busy else tk.DISABLED)
        self.connect_btn.config(state=tk.DISABLED if busy else tk.NORMAL)

        if self.is_downloading:
            self.download_btn.config(state=tk.NORMAL)  # 此时按钮是"取消下载"
        else:
            self.download_btn.config(state=tk.NORMAL if connected and not busy else tk.DISABLED)

        self.upload_btn.config(
            state=tk.NORMAL if connected and not busy and self.current_has_permission else tk.DISABLED
        )

    # ---------- 交互事件 ----------
    def on_item_double_click(self, event=None):
        self._activate_selected()

    def _activate_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        base_name = self.tree.item(item, "text")
        tags = self.tree.item(item, "tags")
        remote = self._row_paths.get(item)

        if "dir" in tags:
            self._navigate_to(remote or self._join_remote(base_name), add_history=True)
        else:
            if messagebox.askyesno("确认下载", f"是否下载文件：\n{base_name}？"):
                self.download_file(base_name, full_path=remote)

    def enter_folder(self, folder_name):
        if self._loading:
            return
        self._navigate_to(self._join_remote(folder_name), add_history=True)

    def go_up(self):
        if self._loading:
            return
        if self.history:
            prev_path = self.history.pop()
            self._navigate_to(prev_path, add_history=False)
        elif self.current_path != "/":
            self._navigate_to(self._parent_remote(self.current_path), add_history=False)

    def refresh(self):
        if not self.client or self._loading:
            return
        self._load_folder(self.current_path, force=True)

    # ---------- 下载核心 ----------
    def download_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中一个文件")
            return

        item = selection[0]
        base_name = self.tree.item(item, "text")
        tags = self.tree.item(item, "tags")

        if "dir" in tags:
            messagebox.showwarning("提示", "目前仅支持下载单个文件，不支持直接下载文件夹。")
            return

        self.download_file(base_name, full_path=self._row_paths.get(item))

    def _find_known_size(self, remote_path):
        for _name, is_dir, size, path in self._current_items:
            if not is_dir and path == remote_path:
                try:
                    return int(size or 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    def download_file(self, base_name, full_path=None):
        if not self.client:
            return

        if self.is_downloading or self.is_uploading:
            messagebox.showwarning("提示", "当前有任务正在进行，请稍后再试。")
            return

        remote_path = full_path or self._join_remote(base_name)
        save_path = filedialog.asksaveasfilename(initialfile=base_name, title="保存文件")
        if not save_path:
            return

        self.is_downloading = True
        self.cancel_flag = False
        self.set_status(f"准备下载 {base_name} ...", "blue")

        self.download_btn.config(text="❌ 取消下载", command=self.cancel_download_action)
        self.progress["value"] = 0
        self.progress_label.config(text="0.0% (0 KB/s)")
        self._set_nav_state()

        expected_size = self._find_known_size(remote_path)
        threading.Thread(
            target=self._do_download_stream,
            args=(remote_path, save_path, base_name, expected_size),
            daemon=True,
        ).start()

    def cancel_download_action(self):
        if self.is_downloading:
            if messagebox.askyesno("取消下载", "确定要终止当前的下载任务吗？"):
                self.cancel_flag = True
                self.set_status("正在取消下载，请稍候...", "orange")
                self.download_btn.config(state=tk.DISABLED)

    def _do_download_stream(self, remote_path, local_path, display_name, expected_size=None):
        client = self.client
        if client is None:
            return
        tmp_path = local_path + ".part"
        response = None
        try:
            total_size = int(expected_size or 0)
            if total_size <= 0:
                try:
                    info = client.info(remote_path)
                    total_size = int(info.get("size") or 0) if info else 0
                except Exception:
                    total_size = 0

            response = client.execute_request(action="download", path=Urn(remote_path).quote())
            response.raise_for_status()
            if total_size <= 0:
                content_length = response.headers.get("content-length")
                if content_length:
                    total_size = int(content_length)

            downloaded = 0
            start_time = time.monotonic()
            last_update_time = 0.0

            with open(tmp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if self.cancel_flag:
                        break
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    current_time = time.monotonic()
                    if current_time - last_update_time > 0.2:
                        elapsed = current_time - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        percent = (downloaded / total_size) * 100 if total_size > 0 else 0
                        self.root.after(0, self._update_progress,
                                        min(percent, 99.9), self.format_speed(speed), "下载")
                        last_update_time = current_time

            if self.cancel_flag:
                self._remove_file(tmp_path)
                self.root.after(0, self._download_done, False, "下载已被手动取消", True)
                return

            # 先写 .part 再原子替换，取消/失败时不会破坏本地同名旧文件
            os.replace(tmp_path, local_path)
            self.root.after(0, self._update_progress, 100.0, "完成", "下载")
            self.root.after(0, self._download_done, True, display_name, False)

        except Exception as exc:
            traceback.print_exc()
            self._remove_file(tmp_path)
            self.root.after(0, self._download_done, False, f"{display_name} 下载失败: {exc}", False)
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    def _update_progress(self, percent, speed, action="下载"):
        self.progress["value"] = percent
        self.progress_label.config(text=f"{percent:.1f}% ({speed})")
        self.set_status(f"正在{action}... {percent:.1f}%", "blue")

    def _download_done(self, success, msg, is_cancelled):
        self.is_downloading = False
        self.cancel_flag = False
        self.download_btn.config(text="📥 下载选中项", command=self.download_selected)
        self.progress["value"] = 0
        self.progress_label.config(text="")
        self._set_nav_state()

        if is_cancelled:
            self.set_status("已取消下载", "orange")
            messagebox.showinfo("已取消", "下载任务已取消，残留文件已清理。")
        elif success:
            self.set_status(f"下载完成: {msg}", "green")
            messagebox.showinfo("下载完成", f"[{msg}] 已成功保存到本地！")
        else:
            self.set_status("下载出错", "red")
            messagebox.showerror("错误", msg)

    # ---------- 上传核心 ----------
    def upload_file(self):
        if not self.client:
            return

        if self.is_downloading or self.is_uploading:
            messagebox.showwarning("提示", "当前有任务正在进行，请稍后再试。")
            return

        local_path = filedialog.askopenfilename(title="选择要上传的文件")
        if not local_path:
            return

        file_size = os.path.getsize(local_path)
        if file_size > MAX_UPLOAD_MB * 1024 * 1024:
            messagebox.showwarning(
                "文件超限",
                f"单次上传最大限制为 {MAX_UPLOAD_MB} MB。\n\n"
                f"您选中的文件大小为 {self.format_size(file_size)}，请重新选择。",
            )
            return

        base_name = os.path.basename(local_path)
        remote_path = self._join_remote(base_name)

        self.is_uploading = True
        self.set_status(f"准备上传 {base_name} ...", "blue")

        self.progress.config(mode="determinate")
        self.progress["value"] = 0
        self.progress_label.config(text="0.0% (0 KB/s)")
        self._set_nav_state()

        threading.Thread(
            target=self._do_upload_task,
            args=(remote_path, local_path, base_name),
            daemon=True,
        ).start()

    def _do_upload_task(self, remote_path, local_path, display_name):
        client = self.client
        if client is None:
            return
        try:
            file_size = os.path.getsize(local_path)
            last_time = time.monotonic()
            last_bytes = 0

            def on_progress(current, total, *args):
                nonlocal last_time, last_bytes
                now = time.monotonic()
                if now - last_time < 0.2 and current < total:
                    return
                percent = (current / total) * 100 if total else 0
                speed = (current - last_bytes) / (now - last_time) if now > last_time else 0
                last_time, last_bytes = now, current
                self.root.after(0, self._update_progress,
                                min(percent, 99.9), self.format_speed(speed), "上传")

            if file_size > 0:
                client.upload_sync(remote_path=remote_path, local_path=local_path, progress=on_progress)
            else:
                # 空文件走无 progress 分支，避免 chunk 生成器处理 0 字节的边界问题
                client.upload_sync(remote_path=remote_path, local_path=local_path)

            self.root.after(0, self._update_progress, 100.0, "完成", "上传")
            self.root.after(0, self._upload_done, True, display_name)
        except Exception as exc:
            traceback.print_exc()
            self.root.after(0, self._upload_done, False,
                            f"[{display_name}] 上传失败\n\n原因: {exc}")

    def _upload_done(self, success, msg):
        self.is_uploading = False

        try:
            self.progress.stop()
        except tk.TclError:
            pass
        self.progress.config(mode="determinate")
        self.progress["value"] = 0
        self.progress_label.config(text="")
        self._set_nav_state()

        if success:
            self.cache.pop(self.current_path, None)
            self.set_status("上传完成", "green")
            messagebox.showinfo("成功", f"文件 [{msg}] 已成功上传！")
            self.refresh()
        else:
            self.set_status("上传失败", "red")
            messagebox.showerror("权限或网络错误", msg)

    # ---------- 退出 ----------
    def on_close(self):
        if self.is_downloading or self.is_uploading:
            if not messagebox.askyesno("退出", "仍有任务正在进行，确定要退出吗？"):
                return
            self.cancel_flag = True
        self.root.destroy()


def main():
    enable_high_dpi()
    root = tk.Tk()
    WebDAVApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
