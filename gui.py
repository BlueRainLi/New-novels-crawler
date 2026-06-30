import sqlite3
import pandas as pd
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttc
import ttkbootstrap.tableview as ttb
from functions import *

col_data = [
    {"text": "Book_id", "stretch": False, "anchor": "center"},
    {"text": "Name", "anchor": "center"},
    {"text": "Author", "anchor": "center"},
    {"text": "Status", "stretch": False, "anchor": "center"},
]

con = sqlite3.connect("book_title_list.db")
cur = con.cursor()
row_data = cur.execute("select * from book").fetchall()
con.close()


class tk_build:
    def __init__(self) -> None:
        self.root = ttk.Window(title="Novels Crawler")
        self.root.geometry("800x600")  # 设置初始窗口大小
        self.root.minsize(600, 400)  # 设置最小窗口大小
        self.colors = self.root.style.colors

        # 配置网格布局权重
        self.root.grid_rowconfigure(0, weight=1)  # 让第一行（Notebook）占据主要空间
        self.root.grid_columnconfigure(0, weight=1)  # 让第一列占据所有可用空间
        for i in range(1, 10):
            self.root.grid_columnconfigure(i, weight=1)

        self.nb = ttk.Notebook(self.root)
        self.nb.grid(row=0, column=0, padx=5, pady=5, sticky="nsew", columnspan=10)

        # 第一个标签页
        self.nb_tab1 = ttk.Frame(self.nb)
        self.nb_tab1.grid_rowconfigure(0, weight=1)
        self.nb_tab1.grid_columnconfigure(0, weight=1)
        self.nb.add(self.nb_tab1, text="Book Menu")

        # 表格视图
        self.nb_tab1_table = ttb.Tableview(
            master=self.nb_tab1,
            coldata=col_data,
            rowdata=row_data,
            paginated=False,
            searchable=True,
            bootstyle=ttc.PRIMARY,
            autoalign=False,
            stripecolor=(self.colors.light, None),  # type: ignore
        )
        self.nb_tab1_table.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # 第二个标签页
        self.nb_tab2 = ttk.Frame(self.nb)
        self.nb_tab2.grid_rowconfigure(0, weight=1)
        self.nb_tab2.grid_columnconfigure(0, weight=1)
        self.nb.add(self.nb_tab2, text="Log")

        # 目录树
        self.tree_frame = ttk.Frame(self.nb_tab2)
        self.tree_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.tree_frame.grid_rowconfigure(0, weight=1)
        self.tree_frame.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(self.tree_frame)
        self.tree.heading("#0", text="Table of Content", anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")

        # 添加滚动条
        self.tree_scroll = ttk.Scrollbar(
            self.tree_frame, orient="vertical", command=self.tree.yview
        )
        self.tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.tree_scroll.set)

        # 底部控件区域
        self.control_frame = ttk.Frame(self.root)
        self.control_frame.grid(
            row=1, column=0, padx=5, pady=5, sticky="ew", columnspan=10
        )
        self.control_frame.grid_columnconfigure(1, weight=1)
        self.control_frame.grid_columnconfigure(3, weight=3)

        self.book_id_label = ttk.Label(self.control_frame, text="Book ID:")
        self.book_id_label.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.book_id_value = ttk.IntVar()
        self.book_id_entry = ttk.Entry(
            self.control_frame, textvariable=self.book_id_value, width=10
        )
        self.book_id_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        self.book_name_label = ttk.Label(self.control_frame, text="Book Name:")
        self.book_name_label.grid(row=0, column=2, padx=5, pady=5, sticky="e")
        self.book_name_value = ttk.StringVar()
        self.book_name_entry = ttk.Entry(
            self.control_frame, textvariable=self.book_name_value, state="readonly"
        )
        self.book_name_entry.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        # 添加控制按钮
        self.refresh_btn = ttk.Button(
            self.control_frame, text="Refresh", bootstyle=ttc.PRIMARY
        )
        self.refresh_btn.grid(row=0, column=4, padx=5, pady=5)

        self.crawl_btn = ttk.Button(
            self.control_frame, text="Crawl", bootstyle=ttc.SUCCESS
        )
        self.crawl_btn.grid(row=0, column=5, padx=5, pady=5)

        self.clear_btn = ttk.Button(
            self.control_frame, text="Clear", bootstyle=ttc.DANGER
        )
        self.clear_btn.grid(row=0, column=6, padx=5, pady=5)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    build = tk_build()
    build.run()
