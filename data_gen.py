"""CellScope data generator.

Creates 200 vehicles x 20 charging sessions = 4,000 sessions.
The data is deterministic (fixed random seeds), so every run gives the same result.
Run this file directly to check the generator without touching the database:
    python data_gen.py
"""
import random
import re
from datetime import datetime, timedelta

STATIONS = [
    ("CS-101", "Bandra Kurla Complex"), ("CS-102", "Powai"), ("CS-103", "Thane"),
    ("CS-104", "Andheri East"), ("CS-105", "Navi Mumbai - Vashi"), ("CS-106", "Lower Parel"),
    ("CS-107", "Borivali"), ("CS-108", "Pune - Hinjewadi"), ("CS-109", "Nashik Road"),
    ("CS-110", "Lonavala Expressway"),
]

# (model, battery capacity in kWh)
MODELS = [
    ("Tata Nexon EV", 40.5), ("Tata Tigor EV", 26), ("Tata Punch EV", 35), ("MG ZS EV", 50.3),
    ("MG Comet EV", 17.3), ("Hyundai Kona Electric", 39.2), ("Mahindra XUV400", 39.4),
    ("BYD Atto 3", 60.5), ("Citroen eC3", 29.2), ("Mahindra BE 6", 59),
]

# (label, base temperature, charging kW, SoH change per session, probability of charging to 100%)
ARCHETYPES = [
    ("Healthy battery", 35, 11, -0.12, 0.1),
    ("Excellent habits", 33, 7, -0.07, 0),
    ("Fast charging, runs hot", 42, 40, -0.35, 0.3),
    ("Declining health", 41, 25, -0.9, 0.5),
    ("Heavy daily use", 38, 22, -0.25, 0.25),
]

# Fixed demo vehicles: plate -> (model, kWh, base temp, kW, SoH slope, full-charge prob, note)
DEMO = {
    "MH01AB1234": ("Tata Nexon EV", 40.5, 36, 12, -0.15, 0.1, "Healthy battery"),
    "MH02CD5678": ("MG ZS EV", 50.3, 42, 40, -0.35, 0.3, "Fast charging, runs hot"),
    "MH03EF9012": ("Hyundai Kona Electric", 39.2, 41, 25, -0.9, 0.5, "Declining health"),
    "MH04GH3456": ("Tata Tigor EV", 26, 33, 7, -0.08, 0, "Excellent habits"),
}

STATES = ["MH", "MH", "MH", "MH", "KA", "DL", "GJ", "TN"]
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
VEHICLE_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$")


def generate(total=200, sessions_per_vehicle=20):
    """Return a list of vehicle dicts, each with its 'sessions' list and a 'pred' value."""
    vehicles, used = [], set(DEMO)

    # 1) the fixed demo vehicles
    for k, (no, (model, kwh, base, kw, slope, full, note)) in enumerate(DEMO.items()):
        vehicles.append(dict(no=no, model=model, kwh=kwh, base=base, kw=kw, slope=slope,
                             full=full, note=note, demo=True, seed=42 + k, soh0=100))

    # 2) random vehicles until we reach `total`
    n = 0
    while len(vehicles) < total:
        n += 1
        r = random.Random(5000 + n)
        no = (r.choice(STATES) + f"{r.randint(1, 49):02d}"
              + r.choice(LETTERS) + r.choice(LETTERS) + str(r.randint(1000, 9999)))
        if no in used:
            continue
        used.add(no)
        model, kwh = r.choice(MODELS)
        note, base, kw, slope, full = r.choice(ARCHETYPES)
        vehicles.append(dict(
            no=no, model=model, kwh=kwh, note=note, demo=False, seed=9000 + n,
            base=round(base + r.gauss(0, 1.5), 1),
            kw=max(3, round(kw + r.gauss(0, 3), 1)),
            slope=round(slope * (0.8 + r.random() * 0.4), 3),
            full=full,
            soh0=min(100, round(100 - r.random() * 10, 1)),
        ))

    # 3) charging sessions and the temperature prediction for each vehicle
    for v in vehicles:
        r = random.Random(v["seed"])
        v["sessions"] = []
        for i in range(sessions_per_vehicle):
            station = r.choice(STATIONS)[0]
            peak = round(v["base"] + r.gauss(0, 2) + v["kw"] / 20, 1)
            v["sessions"].append(dict(
                station=station,
                start=datetime(2026, 6, 1) + timedelta(days=2 * i, hours=r.randint(6, 21),
                                                       minutes=r.randint(0, 59)),
                dur=r.randint(25, 89),
                peak=peak,
                avg=round(peak - 0.5 - r.random() * 1.5, 1),
                kw=round(max(2, v["kw"] + r.gauss(0, 1) * v["kw"] * 0.2), 1),
                soc=100 if r.random() < v["full"] else r.randint(70, 94),
                soh=round(v["soh0"] + v["slope"] * (i + 1) + r.gauss(0, 0.1), 1),
            ))
        # Prediction = average of the last 5 peak temperatures + small offset
        last5 = sum(s["peak"] for s in v["sessions"][-5:]) / 5
        v["pred"] = round(last5 + 0.5 + r.gauss(0, 0.4), 1)
    return vehicles


if __name__ == "__main__":
    data = generate()
    bad = [v for v in data if not VEHICLE_RE.match(v["no"])]
    print("vehicles:", len(data),
          "| unique:", len({v["no"] for v in data}),
          "| sessions:", sum(len(v["sessions"]) for v in data),
          "| bad numbers:", len(bad))
    print("sample:", ", ".join(v["no"] for v in data[:5]))
