"""CellScope - EV Battery Health Monitor (Tkinter GUI).

Run order:
    1) python db.py     (once - creates tables and loads data)
    2) python app.py    (starts the application)
"""
import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
import psycopg2
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import db

HOT_LIMIT, COLD_LIMIT, SOH_REPLACE = 45, 15, 80   # deg C, deg C, % State of Health
NAVY, GREEN, AMBER, RED = "#0f2a43", "#16a34a", "#d97706", "#dc2626"


def health_label(soh):
    """Turn a State-of-Health percentage into (text, colour)."""
    if soh >= 90:
        return "Good", GREEN
    if soh >= SOH_REPLACE:
        return "Fair", AMBER
    return "Poor", RED


# --------------------------------------------------------------------------- logo
class LogoCanvas(tk.Canvas):
    """Battery + lightning-bolt logo drawn with Canvas shapes."""

    def __init__(self, parent):
        super().__init__(parent, width=260, height=56, bg=NAVY, highlightthickness=0)
        self.create_rectangle(8, 14, 52, 44, outline="white", width=3)          # battery body
        self.create_rectangle(52, 22, 58, 36, fill="white", outline="white")    # battery terminal
        self.create_polygon(32, 16, 22, 31, 30, 31, 26, 42, 40, 25, 32, 25,     # lightning bolt
                            fill="#facc15", outline="")
        self.create_text(70, 28, text="CellScope", anchor="w", fill="white",
                         font=("Segoe UI", 20, "bold"))


# --------------------------------------------------------------------------- summary panel
class InfoPanel(ttk.LabelFrame):
    FIELDS = ["Vehicle", "Model", "Battery", "Profile", "Sessions",
              "Latest SoH", "Health", "Thermal alerts", "Predicted next peak"]

    def __init__(self, parent):
        super().__init__(parent, text="Battery summary", padding=8)
        self.values = {}
        for i, name in enumerate(self.FIELDS):
            ttk.Label(self, text=name + ":", font=("Segoe UI", 9, "bold")).grid(
                row=i, column=0, sticky="w", pady=1)
            label = ttk.Label(self, text="-")
            label.grid(row=i, column=1, sticky="w", padx=8)
            self.values[name] = label

    def show(self, d):
        s = d["sessions"]
        soh = s[-1]["soh"]
        health, colour = health_label(soh)
        alerts = sum(1 for x in s if x["peak"] > HOT_LIMIT or x["peak"] < COLD_LIMIT)
        pred = d["pred"]
        pred_text = "-" if pred is None else f"{pred:.1f} C" + ("  (too hot!)" if pred > HOT_LIMIT else "")

        self.values["Vehicle"].config(text=d["vehicle_no"])
        self.values["Model"].config(text=d["model"])
        self.values["Battery"].config(text=f"{d['kwh']} kWh")
        self.values["Profile"].config(text=d["note"] or "-")
        self.values["Sessions"].config(text=str(len(s)))
        self.values["Latest SoH"].config(text=f"{soh:.1f} %  (started at {s[0]['soh']:.1f} %)")
        self.values["Health"].config(text=health, foreground=colour)
        self.values["Thermal alerts"].config(
            text=f"{alerts} of {len(s)} sessions", foreground=RED if alerts else GREEN)
        self.values["Predicted next peak"].config(
            text=pred_text, foreground=RED if pred and pred > HOT_LIMIT else "black")


# --------------------------------------------------------------------------- sessions table
class SessionTable(ttk.Frame):
    COLUMNS = [("no", "#", 35), ("date", "Date", 120), ("loc", "Station", 150), ("dur", "Min", 45),
               ("peak", "Peak C", 60), ("avg", "Avg C", 55), ("kw", "kW", 50),
               ("soc", "SoC %", 55), ("soh", "SoH %", 55)]

    def __init__(self, parent):
        super().__init__(parent)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in self.COLUMNS],
                                 show="headings", height=11)
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="center")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.tag_configure("alert", foreground=RED)

    def load(self, sessions):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(sessions, 1):
            tag = ("alert",) if s["peak"] > HOT_LIMIT or s["peak"] < COLD_LIMIT else ()
            self.tree.insert("", "end", tags=tag, values=(
                i, s["start_time"].strftime("%d-%m-%Y %H:%M"), s["location"], s["duration_min"],
                s["peak"], s["avg"], s["kw"], s["soc"], s["soh"]))


# --------------------------------------------------------------------------- charts
class ChartPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.fig = Figure(figsize=(6, 6), dpi=100)
        self.ax_t = self.fig.add_subplot(211)
        self.ax_h = self.fig.add_subplot(212)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self._frame_axes()
        self.canvas.draw()

    def _frame_axes(self):
        self.ax_t.set_title("Peak temperature per charging session", fontsize=10)
        self.ax_t.set_ylabel("Peak temp (C)")
        self.ax_h.set_title("Battery State of Health (SoH)", fontsize=10)
        self.ax_h.set_xlabel("Charging session #")
        self.ax_h.set_ylabel("SoH (%)")
        for ax in (self.ax_t, self.ax_h):
            ax.grid(alpha=0.3)

    def plot(self, d):
        s = d["sessions"]
        x = list(range(1, len(s) + 1))
        peaks = [r["peak"] for r in s]
        sohs = [r["soh"] for r in s]

        self.ax_t.clear()
        self.ax_h.clear()
        self.ax_t.plot(x, peaks, marker="o", color="#2563eb", label="Peak temp")
        self.ax_t.axhline(HOT_LIMIT, color=RED, linestyle="--", linewidth=1, label=f"Hot limit ({HOT_LIMIT} C)")
        self.ax_t.axhline(COLD_LIMIT, color="#0891b2", linestyle="--", linewidth=1, label=f"Cold limit ({COLD_LIMIT} C)")
        if d["pred"] is not None:
            self.ax_t.scatter([len(s) + 1], [d["pred"]], marker="*", s=180, color=AMBER,
                              zorder=5, label="Predicted next")
        self.ax_t.legend(fontsize=7, loc="upper left")

        self.ax_h.plot(x, sohs, marker="s", color=GREEN, label="SoH")
        self.ax_h.axhline(SOH_REPLACE, color=AMBER, linestyle="--", linewidth=1, label=f"Replace-soon ({SOH_REPLACE} %)")
        self.ax_h.legend(fontsize=7, loc="lower left")

        self._frame_axes()
        self.fig.suptitle(f"{d['vehicle_no']} - {d['model']}", fontsize=11, fontweight="bold")
        self.fig.tight_layout(rect=(0, 0, 1, 0.96))
        self.canvas.draw()


# --------------------------------------------------------------------------- operator window
class FleetWindow(tk.Toplevel):
    def __init__(self, parent, summary):
        super().__init__(parent)
        self.title("Operator view - fleet summary")
        self.geometry("620x420")
        ttk.Label(self, font=("Segoe UI", 11, "bold"), padding=10,
                  text=f"Fleet: {summary['vehicles']} vehicles   |   "
                       f"Thermal alerts logged: {summary['alerts']}").pack(anchor="w")
        ttk.Label(self, text="10 vehicles with the lowest latest SoH:", padding=(10, 0)).pack(anchor="w")
        cols = ("vehicle", "model", "profile", "soh", "peak")
        tree = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for key, title, width in [("vehicle", "Vehicle", 110), ("model", "Model", 150),
                                  ("profile", "Profile", 170), ("soh", "SoH %", 60), ("peak", "Peak C", 60)]:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="center")
        for r in summary["worst"]:
            tree.insert("", "end", values=(r["vehicle_no"], r["model"], r["note"], r["soh"], r["peak"]))
        tree.pack(fill="both", expand=True, padx=10, pady=10)


# --------------------------------------------------------------------------- main window
class CellScopeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CellScope - EV Battery Health Monitor")
        self.geometry("1200x760")
        self.minsize(1000, 650)
        self._build()
        self._load_vehicle_list()

    def _build(self):
        header = tk.Frame(self, bg=NAVY)
        header.pack(fill="x")
        LogoCanvas(header).pack(side="left", padx=10, pady=4)
        tk.Label(header, text="Know your battery. Charge smarter.", bg=NAVY, fg="#cbd5e1",
                 font=("Segoe UI", 10, "italic")).pack(side="left", padx=10)

        controls = ttk.Frame(self, padding=8)
        controls.pack(fill="x")
        ttk.Label(controls, text="Vehicle number:").pack(side="left")
        self.search = ttk.Combobox(controls, width=16)
        self.search.pack(side="left", padx=6)
        self.search.bind("<Return>", lambda _e: self.analyze())
        ttk.Button(controls, text="Analyze", command=self.analyze).pack(side="left")
        self.chips = ttk.Frame(controls)
        self.chips.pack(side="left", padx=15)
        ttk.Button(controls, text="Operator view", command=self.open_fleet).pack(side="right")

        body = ttk.Frame(self, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        self.info = InfoPanel(left)
        self.info.pack(fill="x")
        ttk.Label(left, text="Charging sessions (red = thermal alert)", padding=(0, 8, 0, 2)).pack(anchor="w")
        self.table = SessionTable(left)
        self.table.pack(fill="both", expand=True)

        self.chart = ChartPanel(body)
        self.chart.grid(row=0, column=1, sticky="nsew")

    def _load_vehicle_list(self):
        try:
            self.search["values"] = [r["vehicle_no"] for r in db.list_vehicles(demo_only=False)]
            for r in db.list_vehicles(demo_only=True):
                ttk.Button(self.chips, text=r["vehicle_no"],
                           command=lambda no=r["vehicle_no"]: self.analyze(no)).pack(side="left", padx=2)
        except psycopg2.Error as e:
            messagebox.showerror(
                "Database error",
                "Could not read from PostgreSQL.\n\nCheck that:\n"
                "  1. PostgreSQL is running\n  2. your .env file has the right password\n"
                "  3. you have run:  python db.py\n\nDetails:\n" + str(e).strip())

    def analyze(self, vehicle_no=None):
        no = (vehicle_no or self.search.get()).strip()
        if not no:
            messagebox.showwarning("CellScope", "Enter or pick a vehicle number first.")
            return
        self.search.set(no)
        try:
            data = db.get_vehicle(no)
        except psycopg2.Error as e:
            messagebox.showerror("Database error", str(e).strip())
            return
        if data is None:
            messagebox.showinfo("Not found", f"No vehicle found with number {no.upper()}.")
            return
        self.info.show(data)
        self.table.load(data["sessions"])
        self.chart.plot(data)

    def open_fleet(self):
        try:
            FleetWindow(self, db.fleet_summary())
        except psycopg2.Error as e:
            messagebox.showerror("Database error", str(e).strip())


if __name__ == "__main__":
    CellScopeApp().mainloop()
