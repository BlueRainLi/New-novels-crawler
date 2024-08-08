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

class tk_build():
    def __init__(self) -> None:
        self.root = ttk.Window(title="Novels Crawler")
        self.colors = self.root.style.colors
        self.nb = ttk.Notebook(self.root)
        self.nb_tab1 = ttk.Frame(self.nb)
        self.nb_tab2 = ttk.Frame(self.nb)
        self.nb.pack(fill=ttc.BOTH,expand=True,padx=10, pady=10)
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
        self.nb_tab1_table.pack(fill=ttc.BOTH, expand=True, padx=10, pady=10)
        self.bt1 = ttk.Button(self.nb_tab1, text="test1")
        self.bt1.pack()
        self.nb.add(self.nb_tab1, text="Book Menu")
        self.nb.add(self.nb_tab2, text="Log")


    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    build = tk_build()
    build.run()