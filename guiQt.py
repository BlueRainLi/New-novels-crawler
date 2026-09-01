"""Qt 版小说爬虫 GUI。

布局与交互对齐 gui.py（ttkbootstrap 版）：
顶部 Notebook（书单 / 日志）+ 底部控制栏（按钮行 + 延迟 / 书号 + 书名）。
跟随 Windows 系统深浅色主题启动，并提供手动切换按钮。
在 Windows 11 上额外启用 Mica 云母背板（半透明窗口背景）。
"""

import ast
import ctypes
import queue
import re
import sqlite3
import sys
import threading
import traceback
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from functions import book_title_list, get_ebook

# 界面字体（觉得字小可调大 FONT_SIZE）
FONT_FAMILY = "Microsoft YaHei UI"
FONT_SIZE = 13

# 匹配 get_ebook 的章节输出，如 "[3/42] 第一卷 - 第一章标题"
CHAPTER_RE = re.compile(r"\[(\d+)/(\d+)\] (.+) - (.+)$")
_DONE_MARKER = "__DONE__"
_LINK_COLUMN = 4
_URL_BASE = "https://www.wenku8.net/novel/"
# 链接列的显示文本：用自带颜色的链接图标，一眼看出是可点击链接
_LINK_TEXT = "🔗 打开"

# 深色主题调色板（Fusion 风格）
DARK_PALETTE = {
    "Window": "#353535",
    "WindowText": "#ffffff",
    "Base": "#2b2b2b",
    "AlternateBase": "#333333",
    "Text": "#ffffff",
    "Button": "#3a3a3a",
    "ButtonText": "#ffffff",
    "BrightText": "#ff5252",
    "Highlight": "#2a82da",
    "HighlightedText": "#ffffff",
    "ToolTipBase": "#353535",
    "ToolTipText": "#ffffff",
    "PlaceholderText": "#8a8a8a",
    "Link": "#5a9cf8",
}
# 浅色主题调色板（Fusion 风格）
LIGHT_PALETTE = {
    "Window": "#f5f5f5",
    "WindowText": "#202020",
    "Base": "#ffffff",
    "AlternateBase": "#eeeeee",
    "Text": "#202020",
    "Button": "#e9e9e9",
    "ButtonText": "#202020",
    "BrightText": "#ff0000",
    "Highlight": "#0078d4",
    "HighlightedText": "#ffffff",
    "ToolTipBase": "#ffffdc",
    "ToolTipText": "#000000",
    "PlaceholderText": "#808080",
    "Link": "#1976d2",
}

# 彩色按钮底色：对齐 ttkbootstrap 的 bootstyle 语义
# primary(刷新)=蓝  info(扫描)=青  success(抓取)=绿  danger(清空)=红  secondary(切换)=灰
BUTTON_COLORS = {
    "primary": "#0d6efd",
    "info": "#0d9488",
    "success": "#198754",
    "danger": "#dc3545",
    "secondary": "#6c757d",
}

# 窗口背景不透明度：开启 Mica 后窗口本身半透明，让云母纹理透出来。
# 纯透明(0)会看穿桌面，全不透明(255)会盖住 Mica；200 是深色下的折中值。
MICA_ALPHA = 200


def _windows_build() -> int:
    """返回 Windows 内部版本号；非 Windows 返回 0。"""
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def enable_mica(hwnd: int) -> bool:
    """在 Windows 11 (build 22000+) 上为窗口启用 Mica 背板。成功返回 True。

    保留原生窗口边框时也能生效：Mica 由 DWM 绘制在窗口背后，
    会覆盖标题栏与客户区。需要窗口自身设置 WA_TranslucentBackground。
    """
    if _windows_build() < 22000:
        return False
    try:
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_MAINWINDOW = 2  # Mica
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(ctypes.c_int(DWMSBT_MAINWINDOW)),
            ctypes.sizeof(ctypes.c_int),
        )
        return True
    except Exception:
        return False


def _alpha_color(hex_color: str, alpha: int) -> QColor:
    """把 #RRGGBB 颜色加上 alpha 通道。"""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def style_button(btn: QPushButton, hex_color: str):
    """给按钮套用扁平彩色样式（hover/pressed 自动加深），对齐 ttkbootstrap 风格。"""
    c = QColor(hex_color)
    hover = c.darker(112).name()
    pressed = c.darker(132).name()
    disabled_bg = c.lighter(150).name()
    btn.setStyleSheet(
        f"""
        QPushButton {{
            background-color: {hex_color};
            color: #ffffff;
            border: none;
            padding: 6px 16px;
            border-radius: 4px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {pressed}; }}
        QPushButton:disabled {{ background-color: {disabled_bg}; color: #f0f0f0; }}
        """
    )


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
    """确保本地数据库和 book 表存在（首次运行时自动创建空库）。"""
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
            (book_id, title, author, "可读" if status else "不可读")
            for book_id, title, author, status in rows
        ]
    finally:
        con.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._dark = False
        # Windows 11 上启用 Mica：窗口背景半透明，让 DWM 绘制的云母纹理透出。
        if _windows_build() >= 22000:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._mica_applied = False
        self.setWindowTitle("小说爬虫")
        self.resize(900, 640)
        self.setMinimumSize(640, 440)
        self.setFont(QFont(FONT_FAMILY, FONT_SIZE))

        self.task_running = False
        self.volume_nodes = {}
        self._last_log_item = None
        self._task = None
        self.link_color = QColor(LIGHT_PALETTE["Link"])

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ---------- 顶部：标签页（书单 / 日志） ----------
        self.nb = QTabWidget()
        root.addWidget(self.nb, 1)

        # ---- 标签页 1：书单 ----
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setContentsMargins(0, 0, 0, 0)
        tab1_layout.setSpacing(4)

        # 搜索过滤框
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索："))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按书号 / 书名 / 作者 过滤")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.filter_table)
        search_row.addWidget(self.search_edit, 1)
        tab1_layout.addLayout(search_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["书号", "书名", "作者", "状态", "链接"])
        header = self.table.horizontalHeader()
        # 注意：不要用 ResizeToContents——它会在每次 setItem 时扫描全部行重算列宽，
        # 填 n 行变成 O(n²)，几千本书时刷新会卡几十秒。改为填充后统一 resize 一次。
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self.on_table_select)
        self.table.cellClicked.connect(self.on_table_click)
        tab1_layout.addWidget(self.table, 1)
        self.nb.addTab(tab1, "书单")

        # ---- 标签页 2：日志 ----
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setContentsMargins(0, 0, 0, 0)
        tab2_layout.setSpacing(4)
        tab2_layout.addWidget(QLabel("日志输出"))
        self.log_tree = QTreeWidget()
        self.log_tree.setHeaderHidden(True)
        self.log_tree.setAlternatingRowColors(True)
        tab2_layout.addWidget(self.log_tree, 1)
        self.nb.addTab(tab2, "日志")

        # ---------- 底部控制栏 ----------
        control = QFrame()
        control_layout = QVBoxLayout(control)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(4)

        # ---- 第一行：按钮（左对齐） + 延迟（右对齐） ----
        row1 = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        style_button(self.refresh_btn, BUTTON_COLORS["primary"])
        self.scan_btn = QPushButton("扫描新书")
        style_button(self.scan_btn, BUTTON_COLORS["info"])
        self.crawl_btn = QPushButton("抓取")
        style_button(self.crawl_btn, BUTTON_COLORS["success"])
        self.clear_btn = QPushButton("清空表单")
        style_button(self.clear_btn, BUTTON_COLORS["danger"])
        self.theme_btn = QPushButton("切换深色")
        style_button(self.theme_btn, BUTTON_COLORS["secondary"])
        for btn in (
            self.refresh_btn,
            self.scan_btn,
            self.crawl_btn,
            self.clear_btn,
            self.theme_btn,
        ):
            row1.addWidget(btn)
        row1.addStretch(1)
        row1.addWidget(QLabel("延迟(秒)："))
        self.delay_edit = QLineEdit("5.0")
        self.delay_edit.setFixedWidth(64)
        row1.addWidget(self.delay_edit)
        control_layout.addLayout(row1)

        # ---- 第二行：书号 + 书名 ----
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("书号："))
        self.id_edit = QLineEdit("0")
        self.id_edit.setFixedWidth(96)
        row2.addWidget(self.id_edit)
        row2.addWidget(QLabel("书名："))
        self.name_edit = QLineEdit()
        self.name_edit.setReadOnly(True)
        row2.addWidget(self.name_edit, 1)
        control_layout.addLayout(row2)

        root.addWidget(control)

        # ---------- 信号 ----------
        self.refresh_btn.clicked.connect(self.refresh)
        self.scan_btn.clicked.connect(self.scan_new_books)
        self.crawl_btn.clicked.connect(self.crawl)
        self.clear_btn.clicked.connect(self.clear_form)
        self.theme_btn.clicked.connect(self.toggle_theme)

        self.refresh()

    # ---------- 窗口显示 ----------

    def showEvent(self, event):
        """窗口首次显示时启用 Mica 背板（需要已生成 HWND）。"""
        super().showEvent(event)
        if not self._mica_applied:
            self._mica_applied = enable_mica(int(self.winId()))

    # ---------- 主题 ----------

    def toggle_theme(self):
        """在浅色/深色主题之间手动切换。"""
        self.apply_theme(not self._dark)

    def apply_theme(self, dark: bool):
        """应用指定主题：设置调色板、链接色、按钮文案。"""
        self._dark = dark
        use_mica = _windows_build() >= 22000
        alpha = MICA_ALPHA if use_mica else 255
        palette = QPalette()
        source = DARK_PALETTE if dark else LIGHT_PALETTE
        for name, value in source.items():
            palette.setColor(getattr(QPalette.ColorRole, name), _alpha_color(value, alpha))
        QApplication.instance().setPalette(palette)
        self.link_color = QColor(source["Link"])
        self.theme_btn.setText("切换浅色" if dark else "切换深色")
        self.refresh()

    # ---------- 书单表格 ----------

    def refresh(self):
        rows = fetch_book_rows()
        self._book_rows = rows
        self.table.setRowCount(len(rows))
        for r, (book_id, title, author, status) in enumerate(rows):
            values = [str(book_id), title, author, status]
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if c in (0, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
            link = QTableWidgetItem(_LINK_TEXT)
            link.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            link.setForeground(self.link_color)
            self.table.setItem(r, _LINK_COLUMN, link)
        # 一次性自适应列宽（Stretch 列除外），避免逐行触发 ResizeToContents 的 O(n²) 重算
        for col in (0, 2, 3, _LINK_COLUMN):
            self.table.resizeColumnToContents(col)
        # 刷新后重新应用当前搜索过滤
        self.filter_table(self.search_edit.text())

    def filter_table(self, text: str):
        """按搜索文本过滤表格行（匹配书号/书名/作者/状态，大小写不敏感）。"""
        text = (text or "").strip().lower()
        for r in range(self.table.rowCount()):
            if not text:
                self.table.setRowHidden(r, False)
                continue
            hit = False
            for c in range(4):  # 不含链接列
                item = self.table.item(r, c)
                if item and text in item.text().lower():
                    hit = True
                    break
            self.table.setRowHidden(r, not hit)

    def on_table_select(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._book_rows):
            return
        book_id, title, _, _ = self._book_rows[row]
        self.id_edit.setText(str(book_id))
        self.name_edit.setText(title)

    def on_table_click(self, row: int, column: int):
        """点击链接列时，在浏览器中打开该书在 wenku8 的主页。"""
        if column != _LINK_COLUMN or row < 0 or row >= len(self._book_rows):
            return
        book_id = self._book_rows[row][0]
        webbrowser.open(f"{_URL_BASE}{book_id // 1000}/{book_id}/")

    # ---------- 按钮 ----------

    def _read_delay(self) -> float:
        """读取延迟输入框，解析失败时回退到 5.0。"""
        try:
            return float(self.delay_edit.text().strip())
        except ValueError:
            return 5.0

    def crawl(self):
        try:
            book_id = int(self.id_edit.text().strip())
        except ValueError:
            book_id = 0
        if book_id <= 0:
            QMessageBox.warning(self, "小说爬虫", "请先输入有效的书号。")
            return
        delay = self._read_delay()
        self.crawl_btn.setText("抓取中...")

        def on_done():
            QMessageBox.information(
                self, "小说爬虫", "爬取完成！EPUB 已保存到 epub_output 目录。"
            )

        self.run_background(lambda: get_ebook(book_id, crawl_delay=delay), on_done)

    def scan_new_books(self):
        count, ok = QInputDialog.getInt(
            self, "扫描新书", "从当前最大 ID 往后扫描多少个编号？", 100, 1, 1000000
        )
        if not ok or count <= 0:
            return
        delay = self._read_delay()
        self.scan_btn.setText("扫描中...")

        def on_done():
            self.refresh()
            QMessageBox.information(self, "小说爬虫", "扫描完成，书本列表已刷新。")

        self.run_background(lambda: book_title_list(count, crawl_delay=delay), on_done)

    def clear_form(self):
        """清空表单与日志树，重置表格选中和搜索过滤（不删除数据库数据）。"""
        self.id_edit.setText("0")
        self.name_edit.clear()
        self.log_tree.clear()
        self.volume_nodes = {}
        self._last_log_item = None
        self.table.clearSelection()
        self.search_edit.clear()
        self.filter_table("")

    # ---------- 后台任务与 stdout -> 日志树 ----------

    def run_background(self, fn, on_done):
        self.task_running = True
        self._set_buttons_enabled(False)
        self.log_tree.clear()
        self.volume_nodes = {}
        self._last_log_item = None
        # 任务开始时跳转到日志页查看进度
        self.nb.setCurrentIndex(1)

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
        self._task = (q, state, on_done)
        timer = QTimer(self)
        timer.timeout.connect(lambda: self.process_queue(q, state, on_done))
        timer.start(100)
        self._timer = timer

    def _set_buttons_enabled(self, enabled: bool):
        for btn in (self.refresh_btn, self.scan_btn, self.crawl_btn, self.clear_btn):
            btn.setEnabled(enabled)

    def process_queue(self, q, state, on_done):
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple) and item[0] == _DONE_MARKER:
                state["done"] = True
                state["error"] = item[1]
                continue
            # 一块输出可能包含多行，按行拆分后逐条插入
            for part in str(item).splitlines():
                part = part.strip()
                if part:
                    self.add_log_line(part)
        if state["done"] and q.empty():
            self._timer.stop()
            self.task_running = False
            self._set_buttons_enabled(True)
            self.crawl_btn.setText("抓取")
            self.scan_btn.setText("扫描新书")
            if state["error"] is not None:
                QMessageBox.critical(self, "小说爬虫", f"任务失败：{state['error']}")
            else:
                on_done()
            # 弹窗关闭后跳回书单页
            self.nb.setCurrentIndex(0)
        # 否则保持日志页，等下次轮询

    # ---------- 日志 ----------

    def add_log_line(self, line):
        """解析一行输出：章节行进日志树，新书行格式化，其余作普通日志。"""
        m = CHAPTER_RE.match(line)
        if m:
            volume, title = m.group(3), m.group(4)
            node = self.volume_nodes.get(volume)
            if node is None:
                node = QTreeWidgetItem([volume])
                self.log_tree.addTopLevelItem(node)
                self.volume_nodes[volume] = node
            child = QTreeWidgetItem([title])
            node.addChild(child)
            self._last_log_item = child
            self._auto_scroll()
            return
        if line.startswith("[") and line.endswith("]"):
            try:
                book_id, title, author, status = ast.literal_eval(line)
                status_text = "可读" if status else "不可读"
                self._last_log_item = QTreeWidgetItem(
                    [f"[{book_id}] {title} - {author} ({status_text})"]
                )
                self.log_tree.addTopLevelItem(self._last_log_item)
                self._auto_scroll()
                return
            except (ValueError, SyntaxError):
                pass
        self._last_log_item = QTreeWidgetItem([line])
        self.log_tree.addTopLevelItem(self._last_log_item)
        self._auto_scroll()

    def _auto_scroll(self):
        """新日志到达时自动滚到底部；仅当用户当前停留在最底部时生效。"""
        if self._last_log_item is None:
            return
        bar = self.log_tree.verticalScrollBar()
        if bar.value() >= bar.maximum():
            self.log_tree.scrollToItem(self._last_log_item)

    # ---------- 窗口关闭 ----------

    def closeEvent(self, event):
        if self.task_running:
            answer = QMessageBox.question(
                self,
                "小说爬虫",
                "任务仍在运行，确定要退出吗？未完成的 EPUB 可能不完整。",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


def apply_palette(app: QApplication, window: MainWindow, dark: bool):
    """按深浅色设置调色板（独立函数，便于测试）。

    开启 Mica 时给背景角色加 alpha，让窗口背后的云母纹理透出来；
    未开启 Mica 时 alpha=255 等效于不透明，外观与原来一致。
    """
    window.apply_theme(dark)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(FONT_FAMILY, FONT_SIZE))

    window = MainWindow()
    # 启动时跟随系统深浅色；之后仅由“切换深色/浅色”按钮手动切换（对齐 gui.py）
    dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    apply_palette(app, window, dark)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
