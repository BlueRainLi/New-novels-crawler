"""GUI for the Novels Crawler."""

import ast
import ctypes
import queue
import re
import sqlite3
import sys
import tkinter.font as tkfont
import tkinter as tk
import traceback
import threading
import webbrowser

import ttkbootstrap as ttk
import ttkbootstrap.constants as ttc
from ttkbootstrap.dialogs import Messagebox, Querybox
from ttkbootstrap.widgets.tableview import Tableview

from functions import book_title_list, get_ebook

# Windows 高分屏：让 Tk 跟随系统 DPI 缩放，避免界面字体过小
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# 界面字体设置（觉得字小可以调大 FONT_SIZE）
FONT_FAMILY = "Microsoft YaHei UI"
FONT_SIZE = 13

# 浅色/深色主题对应的 ttkbootstrap 内置主题
LIGHT_THEME = "litera"
DARK_THEME = "darkly"


def windows_app_theme():
    """读取 Windows 应用深浅色设置。

    返回 True 表示浅色、False 表示深色；读取失败或非 Windows 返回 None。
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    return bool(value)
                except OSError:
                    continue
    except OSError:
        pass
    return None


def build_col_data(font) -> list[dict]:
    """按当前字体自适应生成表格列配置，避免字号放大后文字被截断。"""
    return [
        {
            "text": "书号",
            "stretch": False,
            "anchor": "center",
            "width": font.measure("888888") + 16,
        },
        {
            "text": "书名",
            "stretch": True,
            "anchor": "center",
            "minwidth": font.measure("书名") + 24,
        },
        {
            "text": "作者",
            "stretch": False,
            "anchor": "center",
            "width": font.measure("作者作者作者作者") + 16,
        },
        {
            "text": "状态",
            "stretch": False,
            "anchor": "center",
            "width": font.measure("不可读") + 16,
        },
        {
            "text": "链接",
            "stretch": False,
            "anchor": "center",
            "width": font.measure(_LINK_TEXT) + 16,
        },
    ]


# 匹配 get_ebook 的章节输出，如 "[3/42] 第一卷 - 第一章标题"
CHAPTER_RE = re.compile(r"\[(\d+)/(\d+)\] (.+) - (.+)$")
_DONE_MARKER = "__DONE__"
# 链接列的显示文本：用自带颜色的链接图标，一眼看出是可点击链接
_LINK_TEXT = "🔗 打开"


class StdoutRedirector:
    """把 print() 输出同时送进线程安全队列和原始控制台。"""

    def __init__(self, original, q):
        self.original = original
        self.q = q

    def write(self, text):
        self.q.put(text)
        self.original.write(text)

    def flush(self):
        self.original.flush()


def ensure_db():
    """确保本地数据库和 book 表存在（首次运行时 GUI 会创建空库）。"""
    con = sqlite3.connect("book_title_list.db")
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS book
            (id INTEGER PRIMARY KEY,
             title TEXT,
             author TEXT,
             status BOOLEAN)"""
        )
        con.commit()
    finally:
        con.close()


def fetch_book_rows():
    ensure_db()
    con = sqlite3.connect("book_title_list.db")
    try:
        rows = con.execute("select * from book").fetchall()
        return [
            (book_id, title, author, "可读" if status else "不可读", _LINK_TEXT)
            for book_id, title, author, status in rows
        ]
    finally:
        con.close()


class tk_build:
    def __init__(self) -> None:
        # 启动时读取 Windows 应用深浅色，优先跟随系统主题
        self.theme_dark = windows_app_theme() is False
        self.root = ttk.Window(
            title="小说爬虫",
            themename=DARK_THEME if self.theme_dark else LIGHT_THEME,
        )
        # 高分屏下按系统 DPI 缩放初始窗口大小
        dpi_scale = self.root.winfo_fpixels("1i") / 96.0
        self.root.geometry(f"{int(800 * dpi_scale)}x{int(600 * dpi_scale)}")
        self.root.minsize(int(600 * dpi_scale), int(400 * dpi_scale))
        self.colors = self.root.style.colors

        # 统一放大界面字体，行高和列宽随字体自适应
        self.font = tkfont.Font(family=FONT_FAMILY, size=FONT_SIZE)
        # 尽早设置 Tk 默认字体，确保搜索框等控件创建时就使用正确字体
        tkfont.nametofont("TkDefaultFont").configure(family=FONT_FAMILY, size=FONT_SIZE)
        self.root.style.configure("TEntry", font=(FONT_FAMILY, FONT_SIZE))
        self.col_data = build_col_data(self.font)

        # 配置网格布局权重
        self.root.grid_rowconfigure(0, weight=1)  # 第一行（Notebook）占据主要空间
        self.root.grid_columnconfigure(0, weight=1)
        for i in range(1, 10):
            self.root.grid_columnconfigure(i, weight=1)

        self.nb = ttk.Notebook(self.root)
        self.nb.grid(row=0, column=0, padx=5, pady=5, sticky="nsew", columnspan=10)

        # 第一个标签页：书本列表
        self.nb_tab1 = ttk.Frame(self.nb)
        self.nb_tab1.grid_rowconfigure(0, weight=1)
        self.nb_tab1.grid_columnconfigure(0, weight=1)
        self.nb.add(self.nb_tab1, text="书单")

        self.nb_tab1_table = Tableview(
            master=self.nb_tab1,
            coldata=self.col_data,
            rowdata=fetch_book_rows(),
            paginated=False,
            searchable=True,
            yscrollbar=True,
            bootstyle=ttc.PRIMARY,
            autoalign=False,
            stripecolor=(
                (self.colors.dark if self.theme_dark else self.colors.light),
                None,
            ),  # type: ignore
            on_select=self.on_table_select,
        )
        self.nb_tab1_table.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.nb_tab1_table.view.bind("<Button-1>", self.on_table_link_click)

        # 第二个标签页：日志 / 目录树
        self.nb_tab2 = ttk.Frame(self.nb)
        self.nb_tab2.grid_rowconfigure(0, weight=1)
        self.nb_tab2.grid_columnconfigure(0, weight=1)
        self.nb.add(self.nb_tab2, text="日志")

        self.tree_frame = ttk.Frame(self.nb_tab2)
        self.tree_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.tree_frame.grid_rowconfigure(0, weight=1)
        self.tree_frame.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(self.tree_frame)
        self.tree.heading("#0", text="日志输出", anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")

        self.tree_scroll = ttk.Scrollbar(
            self.tree_frame, orient="vertical", command=self.tree.yview
        )
        self.tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.tree_scroll.set)

        # 底部控制栏：书号 / 书名输入 + 按钮
        self.control_frame = ttk.Frame(self.root)
        self.control_frame.grid(
            row=1, column=0, padx=5, pady=5, sticky="ew", columnspan=10
        )
        # 第 5 列（按钮与延迟之间的空白列）占据剩余空间，把延迟推到右侧
        self.control_frame.grid_columnconfigure(5, weight=1)

        # ---- 第一行：按钮（左对齐） ----
        self.refresh_btn = ttk.Button(
            self.control_frame, text="刷新", bootstyle=ttc.PRIMARY, command=self.refresh
        )
        self.refresh_btn.grid(row=0, column=0, padx=5, pady=5)

        self.scan_btn = ttk.Button(
            self.control_frame,
            text="扫描新书",
            bootstyle=ttc.INFO,
            command=self.scan_new_books,
        )
        self.scan_btn.grid(row=0, column=1, padx=5, pady=5)

        self.crawl_btn = ttk.Button(
            self.control_frame, text="抓取", bootstyle=ttc.SUCCESS, command=self.crawl
        )
        self.crawl_btn.grid(row=0, column=2, padx=5, pady=5)

        self.clear_btn = ttk.Button(
            self.control_frame,
            text="清空表单",
            bootstyle=ttc.DANGER,
            command=self.clear,
        )
        self.clear_btn.grid(row=0, column=3, padx=5, pady=5)

        self.theme_btn = ttk.Button(
            self.control_frame,
            text="切换浅色" if self.theme_dark else "切换深色",
            bootstyle=ttc.SECONDARY,
            command=self.toggle_theme,
        )
        self.theme_btn.grid(row=0, column=4, padx=5, pady=5)

        # ---- 第一行右侧：自定义延迟（右对齐） ----
        self.delay_label = ttk.Label(self.control_frame, text="延迟(秒)：")
        self.delay_label.grid(row=0, column=6, padx=(15, 5), pady=5, sticky="e")
        self.delay_value = ttk.DoubleVar(value=5.0)
        self.delay_entry = tk.Entry(
            self.control_frame, textvariable=self.delay_value, width=6,
            font=self.font,
        )
        self.delay_entry.grid(row=0, column=7, padx=5, pady=5, ipadx=4, sticky="w")

        # ---- 第二行：书号 + 书名 ----
        self.book_id_label = ttk.Label(self.control_frame, text="书号：")
        self.book_id_label.grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.book_id_value = ttk.IntVar()
        self.book_id_entry = tk.Entry(
            self.control_frame, textvariable=self.book_id_value, width=8,
            font=self.font,
        )
        self.book_id_entry.grid(row=1, column=1, padx=5, pady=5, ipadx=4, sticky="w")

        self.book_name_label = ttk.Label(self.control_frame, text="书名：")
        self.book_name_label.grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.book_name_value = ttk.StringVar()
        self.book_name_entry = tk.Entry(
            self.control_frame, textvariable=self.book_name_value, state="readonly",
            font=self.font,
        )
        self.book_name_entry.grid(row=1, column=3, padx=5, pady=5, ipadx=4, sticky="ew", columnspan=6)

        self.volume_nodes = {}
        self._last_log_iid = None
        self.task_running = False
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._configure_styles()
        self._apply_entry_colors()
        self._fix_search_entry_font()

    # ---------- 样式 ----------

    def _configure_styles(self):
        """配置字体/行高/表格样式；切换主题后 ttk 会重建样式，需重新调用。"""
        rowheight = self.font.metrics("linespace") + 8
        # 设置 Tk 默认字体，确保所有输入框（含 Tableview 搜索框）字体一致
        tkfont.nametofont("TkDefaultFont").configure(family=FONT_FAMILY, size=FONT_SIZE)
        self.root.style.configure(".", font=(FONT_FAMILY, FONT_SIZE))
        self.root.style.configure(
            "Treeview",
            font=(FONT_FAMILY, FONT_SIZE),
            rowheight=rowheight,
        )
        self.root.style.configure(
            "Treeview.Heading",
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
        )
        self.root.style.configure(
            "TNotebook.Tab",
            font=(FONT_FAMILY, FONT_SIZE),
        )
        self.root.style.configure(
            "TEntry",
            font=(FONT_FAMILY, FONT_SIZE),
            padding=4,
        )

        # Tableview 内部 Treeview 的样式名，兜底统一用 "Table.Treeview"
        table_style = str(self.nb_tab1_table.view.cget("style")) or "Table.Treeview"
        for style_name in (table_style, "Table.Treeview"):
            self.root.style.configure(
                style_name,
                font=(FONT_FAMILY, FONT_SIZE),
                rowheight=rowheight,
            )
            self.root.style.configure(
                f"{style_name}.Heading",
                font=(FONT_FAMILY, FONT_SIZE, "bold"),
            )

    def _apply_entry_colors(self):
        """根据当前主题更新 tk.Entry 颜色，确保暗色模式下可读。"""
        fg = self.colors.inputfg
        bg = self.colors.inputbg
        border = self.colors.selectbg if self.theme_dark else self.colors.border
        for entry in (self.book_id_entry, self.delay_entry, self.book_name_entry):
            entry.configure(
                foreground=fg,
                background=bg,
                insertbackground=fg,
                disabledbackground=bg,
                disabledforeground=fg,
                readonlybackground=bg,
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=border,
                highlightcolor=self.colors.primary,
            )

    def _fix_search_entry_font(self):
        """找到 Tableview 搜索框的 ttk.Entry，用自定义样式确保字体一致。"""
        # 创建自定义样式（切换主题后 ttk 会重置，每次调用都重新配置）
        self.root.style.configure(
            "Search.TEntry",
            font=(FONT_FAMILY, FONT_SIZE),
        )
        # 递归遍历 Tableview 所有子控件，找到所有 ttk.Entry
        def _find_entries(widget):
            found = []
            for child in widget.winfo_children():
                if child.winfo_class() == "TEntry":
                    found.append(child)
                found.extend(_find_entries(child))
            return found

        for entry in _find_entries(self.nb_tab1_table):
            try:
                entry.configure(style="Search.TEntry")
            except Exception:
                pass

    def toggle_theme(self):
        """在浅色/深色主题之间切换。"""
        self.apply_theme(not self.theme_dark)

    def apply_theme(self, dark):
        """应用指定主题，并重建被主题切换重置的样式。"""
        self.theme_dark = dark
        self.root.style.theme_use(DARK_THEME if dark else LIGHT_THEME)
        self.colors = self.root.style.colors
        self._configure_styles()
        self._apply_entry_colors()
        self._fix_search_entry_font()
        stripe = self.colors.dark if dark else self.colors.light
        self.nb_tab1_table.apply_table_stripes((stripe, None))
        self.theme_btn.configure(text="切换浅色" if dark else "切换深色")

    # ---------- 表格 ----------

    def refresh(self):
        """重新从本地数据库加载书本列表。"""
        self.nb.select(self.nb_tab1)
        self.nb_tab1_table.reset_table()
        self.nb_tab1_table.build_table_data(
            coldata=self.col_data, rowdata=fetch_book_rows()
        )

    def on_table_select(self, rows):
        """选中表格行后，自动填充底部的书号和书名。"""
        if not rows:
            return
        values = rows[0].values
        if values:
            self.book_id_value.set(int(values[0]))
            self.book_name_value.set(values[1])

    def on_table_link_click(self, event):
        """点击 Link 列时，在浏览器中打开该书在 wenku8 的主页。"""
        view = self.nb_tab1_table.view
        if view.identify("region", event.x, event.y) != "cell":
            return
        link_cid = f"#{len(view['columns'])}"
        if view.identify_column(event.x) != link_cid:
            return
        iid = view.identify_row(event.y)
        if not iid:
            return
        values = view.item(iid, "values")
        if not values:
            return
        try:
            book_id = int(values[0])
        except (TypeError, ValueError):
            return
        url = f"https://www.wenku8.net/novel/{book_id // 1000}/{book_id}/"
        webbrowser.open(url)

    # ---------- 按钮 ----------

    def crawl(self):
        try:
            book_id = self.book_id_value.get()
        except Exception:
            book_id = 0
        if book_id <= 0:
            Messagebox.show_warning("请先输入有效的书号。", "小说爬虫")
            return
        try:
            delay = self.delay_value.get()
        except Exception:
            delay = 5.0
        self.crawl_btn.configure(text="抓取中...")

        def on_done():
            Messagebox.show_info(
                "爬取完成！EPUB 已保存到 epub_output 目录。", "小说爬虫"
            )

        self.run_background(lambda: get_ebook(book_id, crawl_delay=delay), on_done)

    def scan_new_books(self):
        count = Querybox.get_integer(
            title="扫描新书",
            prompt="从当前最大 ID 往后扫描多少个编号？",
            initialvalue=100,
            minvalue=1,
            parent=self.root,
        )
        if count is None or count <= 0:
            return
        try:
            delay = self.delay_value.get()
        except Exception:
            delay = 5.0
        self.scan_btn.configure(text="扫描中...")

        def on_done():
            self.refresh()
            Messagebox.show_info("扫描完成，书本列表已刷新。", "小说爬虫")

        self.run_background(lambda: book_title_list(count, crawl_delay=delay), on_done)

    def clear(self):
        """清空表单与日志树，重置表格选中和搜索过滤（不删除数据库数据）。"""
        self.book_id_value.set(0)
        self.book_name_value.set("")
        self.tree.delete(*self.tree.get_children())
        self.volume_nodes = {}
        self._last_log_iid = None
        self.nb_tab1_table.selection_clear()
        self.nb_tab1_table.reset_table()

    def on_close(self):
        """关闭窗口前确认：后台任务运行中时提醒用户。"""
        if self.task_running:
            confirm = Messagebox.yesno(
                "任务仍在运行，确定要退出吗？未完成的 EPUB 可能不完整。",
                "小说爬虫",
                parent=self.root,
                localize=False,
            )
            if confirm != "Yes":
                return
        self.root.destroy()

    # ---------- 后台任务：stdout -> Treeview ----------

    def run_background(self, fn, on_done):
        """在后台线程执行 fn，并把它 print 的输出流式显示到 Log 页目录树。"""
        self.task_running = True
        self.crawl_btn.configure(state="disabled")
        self.scan_btn.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.volume_nodes = {}
        self._last_log_iid = None
        self.nb.select(self.nb_tab2)  # 任务开始时跳转到日志页查看进度

        q = queue.Queue()
        old_stdout = sys.stdout
        sys.stdout = StdoutRedirector(old_stdout, q)
        state = {"done": False, "error": None}

        def worker():
            error = None
            try:
                fn()
            except Exception as exc:
                error = exc
                traceback.print_exc(file=old_stdout)
            finally:
                sys.stdout = old_stdout
            q.put((_DONE_MARKER, error))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, lambda: self.process_queue(q, state, on_done))

    def process_queue(self, q, state, on_done):
        """主线程轮询 stdout 队列，逐行更新 Treeview；任务结束后收尾。"""
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple) and item[0] == _DONE_MARKER:
                state["done"] = True
                state["error"] = item[1]
                continue
            # 一块输出可能包含多行（如 traceback），按行拆分后逐条插入
            for part in str(item).splitlines():
                part = part.strip()
                if part:
                    self.add_log_line(part)
        if state["done"] and q.empty():
            self.task_running = False
            self.crawl_btn.configure(state="normal", text="抓取")
            self.scan_btn.configure(state="normal", text="扫描新书")
            if state["error"] is not None:
                Messagebox.show_error(f"任务失败：{state['error']}", "小说爬虫")
            else:
                on_done()
            self.nb.select(self.nb_tab1)  # 弹窗关闭后跳回书单页
        else:
            self.root.after(100, lambda: self.process_queue(q, state, on_done))

    def add_log_line(self, line):
        """解析一行输出：章节行进目录树，新书行格式化，其余作普通日志。"""
        m = CHAPTER_RE.match(line)
        if m:
            volume, title = m.group(3), m.group(4)
            node = self.volume_nodes.get(volume)
            if node is None:
                node = self.tree.insert("", "end", text=volume)
                self.volume_nodes[volume] = node
            self._last_log_iid = self.tree.insert(node, "end", text=title)
            self._auto_scroll()
            return
        if line.startswith("[") and line.endswith("]"):
            try:
                book_id, title, author, status = ast.literal_eval(line)
                status_text = "可读" if status else "不可读"
                self._last_log_iid = self.tree.insert(
                    "", "end", text=f"[{book_id}] {title} - {author} ({status_text})"
                )
                self._auto_scroll()
                return
            except (ValueError, SyntaxError):
                pass
        self._last_log_iid = self.tree.insert("", "end", text=line)
        self._auto_scroll()

    def _auto_scroll(self):
        """新日志到达时自动滚到底部；仅当用户当前停留在最底部时生效。"""
        if self._last_log_iid and self.tree.yview()[1] >= 1.0:
            self.tree.see(self._last_log_iid)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    build = tk_build()
    build.run()
