import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, Menu
import threading
import time
import posixpath
import os
import traceback
from webdav3.client import Client

class WebDAVApp:
    def __init__(self, root):
        self.root = root
        self.root.title("便携 WebDAV 客户端 Pro")
        self.root.geometry("850x650")
        self.center_window(850, 650)
        
        # 启用更现代的内置主题
        style = ttk.Style()
        if 'clam' in style.theme_names():
            style.theme_use('clam')
            
        # 自定义 Treeview 样式
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei", 10, "bold"), background="#e1e1e1")
        style.map("Treeview", background=[('selected', '#4361ee')])

        self.client = None
        self.current_path = '/'
        self.history = []               # 浏览历史
        self.cache = {}                  # 路径 -> 文件列表缓存

        self.create_widgets()
        self.create_context_menu()

    def create_widgets(self):
        # ========== 顶部：连接配置区域 ==========
        config_frame = ttk.LabelFrame(self.root, text=" 连接配置 ", padding=(15, 10))
        config_frame.grid(row=0, column=0, padx=15, pady=10, sticky="ew")
        self.root.grid_columnconfigure(0, weight=1)

        ttk.Label(config_frame, text="WebDAV 地址:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.url_entry = ttk.Entry(config_frame, width=50)
        self.url_entry.insert(0, "https://webdav.123pan.cn/webdav")
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, sticky="we")

        ttk.Label(config_frame, text="用户名:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        default_user = "webdavUser" # 请替换为真实用户名
        self.real_username = default_user
        self.placeholder_username = self.mask_username(default_user)
        
        self.user_entry = ttk.Entry(config_frame, width=50, foreground='gray')
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

        # ========== 路径显示 ==========
        path_frame = ttk.Frame(self.root)
        path_frame.grid(row=2, column=0, padx=15, pady=(0, 5), sticky="ew")
        self.path_label = ttk.Label(path_frame, text="当前路径: /", font=("Microsoft YaHei", 9, "bold"), foreground="#4361ee")
        self.path_label.pack(side=tk.LEFT)

        # ========== 文件列表 (Treeview 优化) ==========
        list_frame = ttk.Frame(self.root)
        list_frame.grid(row=3, column=0, padx=15, pady=5, sticky="nsew")
        self.root.grid_rowconfigure(3, weight=1)

        # 创建多列视图
        columns = ("name", "type", "size")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("name", text="文件名称", anchor=tk.W)
        self.tree.heading("type", text="类型", anchor=tk.CENTER)
        self.tree.heading("size", text="大小", anchor=tk.E)
        
        self.tree.column("name", width=500, anchor=tk.W)
        self.tree.column("type", width=100, anchor=tk.CENTER)
        self.tree.column("size", width=120, anchor=tk.E)

        # 滚动条
        y_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 绑定事件
        self.tree.bind("<Double-1>", self.on_item_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu) # 右键菜单

        # ========== 底部：进度条与状态栏 ==========
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.grid(row=4, column=0, padx=15, pady=10, sticky="ew")
        
        self.status = ttk.Label(bottom_frame, text="就绪", foreground="gray")
        self.status.pack(side=tk.LEFT)

        self.progress_label = ttk.Label(bottom_frame, text="", font=("Courier", 9))
        self.progress_label.pack(side=tk.RIGHT, padx=5)

        self.progress = ttk.Progressbar(bottom_frame, orient=tk.HORIZONTAL, length=300, mode='determinate')
        self.progress.pack(side=tk.RIGHT, padx=10)

    def create_context_menu(self):
        """创建右键菜单"""
        self.context_menu = Menu(self.root, tearoff=0, font=("Microsoft YaHei", 9))
        self.context_menu.add_command(label="📥 下载选中文件", command=self.download_selected)
        self.context_menu.add_command(label="📋 复制文件名称", command=self.copy_filename)

    # ---------- 工具函数 ----------
    def center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def mask_username(self, username):
        if len(username) == 11 and username.isdigit():
            return username[:3] + "****" + username[-4:]
        return username

    def on_user_focus_in(self, event):
        current = self.user_entry.get()
        if current == self.placeholder_username:
            self.user_entry.delete(0, tk.END)
            self.user_entry.config(foreground='black')

    def on_user_focus_out(self, event):
        current = self.user_entry.get().strip()
        if not current:
            self.user_entry.insert(0, self.placeholder_username)
            self.user_entry.config(foreground='gray')

    def set_status(self, text, color="black"):
        self.status.config(text=text, foreground=color)
        self.root.update_idletasks()

    # ---------- 交互事件 ----------
    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def copy_filename(self):
        selection = self.tree.selection()
        if selection:
            item = selection[0]
            base_name = self.tree.item(item, "text") # text存储了真实的纯文件名
            self.root.clipboard_clear()
            self.root.clipboard_append(base_name)
            self.set_status(f"已复制: {base_name}", "green")

    def jump_to_path(self):
        path = simpledialog.askstring("跳转路径", "请输入目标路径（如 /app/Windows）：", initialvalue=self.current_path)
        if not path: return
        path = path.strip()
        if not path.startswith('/'): path = '/' + path

        self.set_status(f"正在验证路径 {path} ...")
        self.tree.delete(*self.tree.get_children())
        threading.Thread(target=self._jump_to_path_worker, args=(path,)).start()

    def _jump_to_path_worker(self, path):
        try:
            files = self.client.list(path)
            self.root.after(0, self._jump_success, path, files)
        except Exception as e:
            self.root.after(0, self._jump_fail, path, str(e))

    def _jump_success(self, path, files):
        self.cache[path] = files
        self.current_path = path
        self.history.clear()
        self._update_file_list(files)
        self.set_status(f"已跳转到 {path}", "green")

    def _jump_fail(self, path, error):
        messagebox.showerror("错误", f"无法访问路径 {path}\n{error}")
        self._load_folder(self.current_path)

    # ---------- 连接与列表渲染 ----------
    def connect(self):
        url = self.url_entry.get().strip()
        input_user = self.user_entry.get().strip()
        user = self.real_username if input_user == self.placeholder_username else input_user
        self.real_username = user
        pwd = self.pwd_entry.get().strip()

        if not url or not user or not pwd:
            messagebox.showwarning("提示", "请填写完整的地址、用户名和密码")
            return

        self.connect_btn.config(state=tk.DISABLED, text="连接中...")
        self.set_status("正在连接服务器...", "blue")
        threading.Thread(target=self._do_connect, args=(url, user, pwd), daemon=True).start()

    def _do_connect(self, url, user, pwd):
        try:
            options = {
                'webdav_hostname': url,
                'webdav_login': user,
                'webdav_password': pwd
            }
            self.client = Client(options)
            files = self.client.list('/') 
            self.cache.clear()
            self.cache['/'] = files
            self.current_path = '/'
            self.history.clear()
            self.root.after(0, self._update_file_list, files)
        except Exception as e:
            self.root.after(0, messagebox.showerror, "连接失败", str(e))
            self.root.after(0, self.set_status, "连接失败", "red")
            self.root.after(0, lambda: self.connect_btn.config(state=tk.NORMAL, text="🔌 连接服务器"))

    def _update_file_list(self, files):
            self.tree.delete(*self.tree.get_children())
            items_info = []

            # 获取当前所在目录的纯名称 (例如从 /app/Windows/ 中提取出 Windows)
            current_basename = posixpath.basename(self.current_path.rstrip('/'))
            skipped_self = False # 标记：确保只过滤一次当前目录本身

            for entry in files:
                entry = entry.strip()
                if not entry or entry == '/': continue

                raw_name = entry.rstrip('/')
                base_name = posixpath.basename(raw_name)
                if not base_name: continue

                # 比对纯名称，并且只忽略第一次碰到的自己
                if not skipped_self and base_name == current_basename:
                    skipped_self = True
                    continue

                is_dir = entry.endswith('/')
                items_info.append((base_name, is_dir))

            items_info.sort(key=lambda x: (not x[1], x[0].lower()))

            for base_name, is_dir in items_info:
                icon = "📁" if is_dir else "📄"
                type_str = "文件夹" if is_dir else "文件"
                # text 属性保存真实的纯文件名，values 存储显示在列中的数据
                self.tree.insert("", tk.END, text=base_name, values=(f"{icon}  {base_name}", type_str, "-"), tags=('dir' if is_dir else 'file',))

            self.path_label.config(text=f"当前路径: {self.current_path}")
            self.up_btn.config(state=tk.NORMAL if self.current_path != '/' else tk.DISABLED)
            self.download_btn.config(state=tk.NORMAL)
            self.refresh_btn.config(state=tk.NORMAL)
            self.jump_btn.config(state=tk.NORMAL)
            self.connect_btn.config(state=tk.NORMAL, text="🔌 重新连接")
            self.set_status("列表加载完成", "green")

    def _load_folder(self, path):
        if path in self.cache:
            self.root.after(0, self._update_file_list, self.cache[path])
            return

        self.set_status(f"正在加载 {path} ...", "blue")
        try:
            files = self.client.list(path)
            self.cache[path] = files
            self.root.after(0, self._update_file_list, files)
        except Exception as e:
            self.root.after(0, messagebox.showerror, "加载失败", str(e))
            self.root.after(0, self.set_status, "加载失败", "red")

    def on_item_double_click(self, event):
        selection = self.tree.selection()
        if not selection: return
        item = selection[0]
        base_name = self.tree.item(item, "text")
        tags = self.tree.item(item, "tags")
        
        if 'dir' in tags:
            self.enter_folder(base_name)
        else:
            if messagebox.askyesno("确认下载", f"是否下载文件：\n{base_name}？"):
                self.download_file(base_name)

    def enter_folder(self, folder_name):
        new_path = '/' + folder_name if self.current_path == '/' else self.current_path.rstrip('/') + '/' + folder_name
        self.tree.delete(*self.tree.get_children())
        self.history.append(self.current_path)
        self.current_path = new_path
        threading.Thread(target=self._load_folder, args=(new_path,), daemon=True).start()

    def go_up(self):
        if self.history:
            prev_path = self.history.pop()
            self.current_path = prev_path
            self._load_folder(prev_path)
        elif self.current_path != '/':
            self.current_path = '/'
            self._load_folder('/')

    def refresh(self):
        if self.current_path in self.cache:
            del self.cache[self.current_path]
        self._load_folder(self.current_path)

    # ---------- 下载核心 ----------
    def download_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中一个文件")
            return
            
        item = selection[0]
        base_name = self.tree.item(item, "text")
        tags = self.tree.item(item, "tags")
        
        if 'dir' in tags:
            messagebox.showwarning("提示", "目前仅支持下载单个文件，不支持直接下载文件夹。")
            return
            
        self.download_file(base_name)

    def download_file(self, base_name):
        if not self.client: return

        remote_path = '/' + base_name if self.current_path == '/' else self.current_path.rstrip('/') + '/' + base_name
        save_path = filedialog.asksaveasfilename(initialfile=base_name, title="保存文件")
        if not save_path: return

        self.set_status(f"准备下载 {base_name} ...", "blue")
        self.download_btn.config(state=tk.DISABLED)
        self.progress['value'] = 0
        self.progress_label.config(text="0.0% (0 KB/s)")

        threading.Thread(target=self._do_download, args=(remote_path, save_path, base_name), daemon=True).start()

    def _do_download(self, remote_path, local_path, display_name):
        try:
            info = self.client.info(remote_path)
            total_size = int(info.get('size', 0)) if info else 0

            self.download_complete = False
            self.download_error = None

            def download_task():
                try:
                    self.client.download(remote_path, local_path)
                    self.download_complete = True
                except Exception as e:
                    self.download_error = e
                    self.download_complete = True

            threading.Thread(target=download_task, daemon=True).start()

            start_time = time.time()
            while not self.download_complete:
                if os.path.exists(local_path):
                    downloaded = os.path.getsize(local_path)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        elapsed = time.time() - start_time
                        speed = downloaded / elapsed / 1024 / 1024 if elapsed > 0 else 0 # 转换成 MB/s
                        speed_str = f"{speed:.2f} MB/s" if speed > 1 else f"{speed * 1024:.1f} KB/s"
                        self.root.after(0, self._update_progress, percent, speed_str)
                time.sleep(0.3)

            if self.download_error:
                raise self.download_error
            else:
                self.root.after(0, self._download_done, True, display_name)

        except Exception as e:
            traceback.print_exc()
            self.root.after(0, self._download_done, False, f"{display_name} 下载失败: {str(e)}")

    def _update_progress(self, percent, speed):
        self.progress['value'] = percent
        self.progress_label.config(text=f"{percent:.1f}% ({speed})")
        self.set_status(f"正在下载... {percent:.1f}%", "blue")

    def _download_done(self, success, msg):
        self.download_btn.config(state=tk.NORMAL)
        self.progress['value'] = 0
        self.progress_label.config(text="")
        if success:
            self.set_status(f"下载完成: {msg}", "green")
            messagebox.showinfo("下载完成", f"[{msg}] 已成功保存到本地！")
        else:
            self.set_status("下载出错", "red")
            messagebox.showerror("错误", msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = WebDAVApp(root)
    root.mainloop()