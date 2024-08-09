import pandas as pd
import ttkbootstrap as ttk
import ttkbootstrap.constants as ttc
import ttkbootstrap.tableview as ttb

col_data = [
    {"text": "id", "stretch": False, "anchor":"center"},
    {"text":"Name", "anchor": "center"},
    {"text":"Author", "anchor":"center"},
    {"text": "Status", "stretch": False, "anchor":"center"}
]

data = pd.read_csv("book_menu.csv")
row_data = []
for index, row in data.iterrows():
    row_data.append((row.iloc[0], row.iloc[1], row.iloc[2], row.iloc[3]))
print(row_data)

class tk_build():
    def __init__(self) -> None:
        self.root = ttk.Window(title="Novels Crawler")
        self.colors = self.root.style.colors
        self.nb = ttk.Notebook(self.root)
        self.nb_tab1 = ttk.Frame(self.nb)
        self.nb_tab1.grid(row=0, column=0, padx=5, sticky='nsew')
        self.nb_tab2 = ttk.Frame(self.nb)
        self.nb_tab2.grid(row=0, column=0, padx=5, sticky='nsew')
        self.nb.grid(row=0,column=0,padx=5,pady=5,sticky='nsew',columnspan=10)
        self.nb_tab1_table = ttb.Tableview(
            master=self.nb_tab1,
            coldata=col_data,
            rowdata=row_data,
            paginated=False,
            searchable=True,
            bootstyle=ttc.PRIMARY,
            autoalign=False,
            stripecolor=(self.colors.light, None),
        )
        self.nb_tab1_table.pack(fill="x")
        self.nb.add(self.nb_tab1, text="Book Menu")
        self.nb.add(self.nb_tab2, text="Log")

        self.book_id_label = ttk.Label(self.root, text="Book ID:")
        self.book_id_label.grid(row=1,column=0,padx=5,pady=5,sticky='nsew')
        self.book_id_value = ttk.StringVar()
        self.book_id_entry = ttk.Entry(self.root, textvariable=self.book_id_value,width=5)
        self.book_id_entry.grid(row=1,column=1,padx=5,pady=5,sticky='nsew')
        self.book_name_label = ttk.Label(self.root, text="Book Name:")
        self.book_name_label.grid(row=1,column=2,padx=5,pady=5,sticky='nsew')
        self.book_name_value = ttk.StringVar()
        self.book_name_entry = ttk.Entry(self.root, textvariable=self.book_name_value, state="readonly")
        self.book_name_entry.grid(row=1,column=3,padx=5,pady=5,sticky='nsew')

        self.tree = ttk.Treeview(self.nb_tab2)
        self.tree.heading("#0", text="Table of Content", anchor='w')
        self.tree.pack(fill='x')
    


    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    build = tk_build()
    build.run()