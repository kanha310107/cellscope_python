"""CellScope database layer (PostgreSQL via psycopg2).

Run this file once to create the tables and load the data:
    python db.py
"""
import os

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from data_gen import STATIONS, generate


def _load_env(filename=".env"):
    """Tiny .env reader (no extra package). Lines look like KEY=value."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicle (
  vehicle_no  text PRIMARY KEY CHECK (vehicle_no ~ '^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}$'),
  model       text NOT NULL,
  battery_kwh numeric(6,1) NOT NULL CHECK (battery_kwh > 0),
  note        text,
  is_demo     boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS charging_station (
  station_id text PRIMARY KEY,
  location   text NOT NULL
);

CREATE TABLE IF NOT EXISTS charging_session (
  session_id   serial PRIMARY KEY,
  vehicle_no   text NOT NULL REFERENCES vehicle(vehicle_no) ON DELETE CASCADE,
  station_id   text NOT NULL REFERENCES charging_station(station_id),
  start_time   timestamptz NOT NULL,
  duration_min int NOT NULL CHECK (duration_min > 0),
  peak_temp    numeric(4,1) NOT NULL,
  avg_temp     numeric(4,1) NOT NULL,
  avg_kw       numeric(5,1) NOT NULL CHECK (avg_kw >= 0),
  end_soc      int NOT NULL CHECK (end_soc BETWEEN 0 AND 100),
  est_soh      numeric(4,1) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_vehicle_time ON charging_session (vehicle_no, start_time);

CREATE TABLE IF NOT EXISTS prediction (
  vehicle_no          text PRIMARY KEY REFERENCES vehicle(vehicle_no) ON DELETE CASCADE,
  predicted_peak_temp numeric(4,1) NOT NULL,
  based_on_session_id int REFERENCES charging_session(session_id),
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW v_thermal_alerts AS
SELECT s.*, CASE WHEN peak_temp > 45 THEN 'too_hot' ELSE 'too_cold' END AS alert_type
FROM charging_session s
WHERE peak_temp > 45 OR peak_temp < 15;
"""


def get_conn():
    # An empty DSN makes psycopg2 use PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD
    return psycopg2.connect(os.environ.get("DATABASE_URL", ""))


def seed():
    """Create tables, wipe old rows, and load 200 vehicles / 4,000 sessions."""
    vehicles = generate(200)
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:  # one transaction: commits on success, rolls back on error
            cur.execute(SCHEMA)
            cur.execute("TRUNCATE prediction, charging_session, charging_station, vehicle RESTART IDENTITY CASCADE")
            execute_values(cur, "INSERT INTO charging_station VALUES %s", STATIONS)

            for v in vehicles:
                cur.execute(
                    "INSERT INTO vehicle (vehicle_no, model, battery_kwh, note, is_demo) VALUES (%s,%s,%s,%s,%s)",
                    (v["no"], v["model"], v["kwh"], v["note"], v["demo"]))
                rows = [(v["no"], s["station"], s["start"], s["dur"], s["peak"],
                         s["avg"], s["kw"], s["soc"], s["soh"]) for s in v["sessions"]]
                ids = execute_values(
                    cur,
                    "INSERT INTO charging_session (vehicle_no, station_id, start_time, duration_min, "
                    "peak_temp, avg_temp, avg_kw, end_soc, est_soh) VALUES %s RETURNING session_id",
                    rows, fetch=True)
                last_id = max(r[0] for r in ids)
                cur.execute(
                    "INSERT INTO prediction (vehicle_no, predicted_peak_temp, based_on_session_id) "
                    "VALUES (%s,%s,%s)", (v["no"], v["pred"], last_id))
        print(f"Seeded {len(vehicles)} vehicles and {len(vehicles) * 20} sessions.")
    finally:
        conn.close()


def list_vehicles(demo_only=True):
    """Vehicle numbers (and notes) for the search box and demo buttons."""
    sql = ("SELECT vehicle_no, note FROM vehicle "
           + ("WHERE is_demo " if demo_only else "") + "ORDER BY vehicle_no")
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()
    finally:
        conn.close()


def get_vehicle(vehicle_no):
    """One vehicle with all its sessions and its prediction, or None if not found."""
    no = vehicle_no.upper().replace(" ", "")
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM vehicle WHERE vehicle_no = %s", (no,))
            v = cur.fetchone()
            if not v:
                return None
            cur.execute("""
                SELECT s.session_id, s.start_time, s.duration_min, s.station_id, st.location,
                       s.peak_temp::float AS peak, s.avg_temp::float AS avg,
                       s.avg_kw::float AS kw, s.end_soc AS soc, s.est_soh::float AS soh
                FROM charging_session s JOIN charging_station st USING (station_id)
                WHERE s.vehicle_no = %s ORDER BY s.start_time, s.session_id""", (no,))
            sessions = cur.fetchall()
            cur.execute("SELECT predicted_peak_temp::float AS t FROM prediction WHERE vehicle_no = %s", (no,))
            p = cur.fetchone()
            return {"vehicle_no": no, "model": v["model"], "kwh": float(v["battery_kwh"]),
                    "note": v["note"], "sessions": sessions, "pred": p["t"] if p else None}
    finally:
        conn.close()


def fleet_summary(limit=10):
    """Operator view: fleet size, total thermal alerts, and the vehicles with the lowest latest SoH."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT count(*) AS n FROM vehicle")
            vehicles = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM v_thermal_alerts")
            alerts = cur.fetchone()["n"]
            cur.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (s.vehicle_no)
                           s.vehicle_no, v.model, v.note,
                           s.est_soh::float AS soh, s.peak_temp::float AS peak
                    FROM charging_session s JOIN vehicle v USING (vehicle_no)
                    ORDER BY s.vehicle_no, s.start_time DESC
                ) latest
                ORDER BY soh ASC LIMIT %s""", (limit,))
            worst = cur.fetchall()
        return {"vehicles": vehicles, "alerts": alerts, "worst": worst}
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
    print("Demo vehicles:", [r["vehicle_no"] for r in list_vehicles()])
    print("Sessions for MH03EF9012:", len(get_vehicle("MH03EF9012")["sessions"]))
