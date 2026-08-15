"""Qt 版小说爬虫 GUI。

布局：顶部输入框 + 按钮，中部书单表格，底部日志树。
跟随 Windows 系统深浅色主题，Qt 自动处理高分屏 DPI。
使用原生窗口边框与标题栏。
"""

import ast
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
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
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
FONT_SIZE = 11

# 匹配 get_ebook 的章节输出，如 "[3/42] 第一卷 - 第一章标题"
CHAPTER_RE = re.compile(r"\[(\d+)/(\d+)\] (.+) - (.+)$")
_DONE_MARKER = "__DONE__"
_LINK_COLUMN = 4
_URL_BASE = "https://www.wenku8.net/novel/"

# 深色主题调色板（Fusion 风格）
DARK_PALETTE = {
    "Window": "#353535",
    "WindowText": "#ffffff",
    "Base": "#2b2b2b",
    "AlternateBase": "#353535",
    "Text": "#ffffff",
    "Button": "#353535",
    "ButtonText": "#ffffff",
    "BrightText": "#ff5252",
    "Highlight": "#2a82da",
    "HighlightedText": "#ffffff",
    "ToolTipBase": "#353535",
    "ToolTipText": "#ffffff",
    "PlaceholderText": "#8a8a8a",
    "Link": "#5a9cf8",
}
LIGHT_LINK_COLOR = "#1976d2"


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
        self.setWindowTitle("小说爬虫")
        self.resize(1000, 720)
        self.setFont(QFont(FONT_FAMILY, FONT_SIZE))

        self.task_running = False
        self.volume_nodes = {}
        self._last_log_item = None
        self._task = None
        self.link_color = QColor(LIGHT_LINK_COLOR)

        self.setMinimumSize(720, 480)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---------- 顶部：输入框 ----------
        top1 = QHBoxLayout()
        self.id_label = QLabel("书号：")
        self.id_edit = QLineEdit()
        self.id_edit.setFixedWidth(120)
        self.name_label = QLabel("书名：")
        self.name_edit = QLineEdit()
        self.name_edit.setReadOnly(True)
        top1.addWidget(self.id_label)
        top1.addWidget(self.id_edit)
        top1.addWidget(self.name_label)
        top1.addWidget(self.name_edit, 1)
        root.addLayout(top1)

        # ---------- 顶部：按钮 ----------
        top2 = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.scan_btn = QPushButton("扫描新书")
        self.crawl_btn = QPushButton("抓取")
        self.clear_btn = QPushButton("清空表单")
        for btn in (self.refresh_btn, self.scan_btn, self.crawl_btn, self.clear_btn):
            top2.addWidget(btn)
        top2.addStretch(1)
        root.addLayout(top2)

        # ---------- 中部表格 / 底部日志 ----------
        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, 1)

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
        splitter.addWidget(self.table)

        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(QLabel("日志输出"))
        self.log_tree = QTreeWidget()
        self.log_tree.setHeaderHidden(True)
        self.log_tree.setAlternatingRowColors(True)
        log_layout.addWidget(self.log_tree)
        splitter.addWidget(log_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # ---------- 信号 ----------
        self.refresh_btn.clicked.connect(self.refresh)
        self.scan_btn.clicked.connect(self.scan_new_books)
        self.crawl_btn.clicked.connect(self.crawl)
        self.clear_btn.clicked.connect(self.clear_form)

        self.refresh()

    # ---------- 主题 ----------

    def on_theme_changed(self, dark: bool):
        """系统深浅色主题变化时更新链接列颜色。"""
        self._dark = dark
        self.link_color = QColor(DARK_PALETTE["Link"] if dark else LIGHT_LINK_COLOR)
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
            link = QTableWidgetItem("打开 ↗")
            link.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            link.setForeground(self.link_color)
            self.table.setItem(r, _LINK_COLUMN, link)
        # 一次性自适应列宽（Stretch 列除外），避免逐行触发 ResizeToContents 的 O(n²) 重算
        for col in (0, 2, 3, _LINK_COLUMN):
            self.table.resizeColumnToContents(col)

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

    def crawl(self):
        try:
            book_id = int(self.id_edit.text().strip())
        except ValueError:
            book_id = 0
        if book_id <= 0:
            QMessageBox.warning(self, "小说爬虫", "请先输入有效的书号。")
            return
        self.crawl_btn.setText("抓取中...")

        def on_done():
            QMessageBox.information(
                self, "小说爬虫", "爬取完成！EPUB 已保存到 epub_output 目录。"
            )

        self.run_background(lambda: get_ebook(book_id), on_done)

    def scan_new_books(self):
        count, ok = QInputDialog.getInt(
            self, "扫描新书", "从当前最大 ID 往后扫描多少个编号？", 100, 1, 1000000
        )
        if not ok or count <= 0:
            return
        self.scan_btn.setText("扫描中...")

        def on_done():
            self.refresh()
            QMessageBox.information(self, "小说爬虫", "扫描完成，书本列表已刷新。")

        self.run_background(lambda: book_title_list(count), on_done)

    def clear_form(self):
        self.id_edit.clear()
        self.name_edit.clear()
        self.log_tree.clear()
        self.volume_nodes = {}
        self._last_log_item = None
        self.table.clearSelection()

    # ---------- 后台任务与 stdout -> 日志树 ----------

    def run_background(self, fn, on_done):
        self.task_running = True
        self._set_buttons_enabled(False)
        self.log_tree.clear()
        self.volume_nodes = {}
        self._last_log_item = None

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
    """按深浅色设置调色板（独立函数，便于测试）。"""
    if dark:
        palette = QPalette()
        for name, value in DARK_PALETTE.items():
            palette.setColor(getattr(QPalette.ColorRole, name), QColor(value))
        app.setPalette(palette)
    else:
        app.setPalette(app.style().standardPalette())
    window.on_theme_changed(dark)


def apply_system_theme(app: QApplication, window: MainWindow):
    """根据 Windows 系统深浅色主题设置 Qt 调色板，并监听系统主题切换。"""

    def update_theme():
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        apply_palette(app, window, dark)

    app.styleHints().colorSchemeChanged.connect(update_theme)
    update_theme()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(FONT_FAMILY, FONT_SIZE))

    window = MainWindow()
    apply_system_theme(app, window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
