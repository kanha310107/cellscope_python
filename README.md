# CellScope (Python) - EV Battery Health Monitor

A Python + PostgreSQL + Tkinter desktop app that tracks EV battery health from charging sessions:
peak temperature, State of Health (SoH), thermal alerts and a next-session temperature prediction.
It is a Python version of the original Node.js CellScope project.

## Files
| File | Purpose |
|---|---|
| `data_gen.py` | Generates 200 vehicles x 20 charging sessions (fixed seeds, so results repeat) |
| `db.py` | PostgreSQL schema, seeding, and query functions |
| `app.py` | Tkinter GUI: search, summary, session table, charts, operator view |
| `requirements.txt` | Python packages to install |
| `env.example` | Template for your database settings (copy to `.env`) |

## Setup
1. Install PostgreSQL and create the database:
   `createdb -U postgres cellscope`
2. Install packages:
   `pip install -r requirements.txt`
3. Copy `env.example` to `.env` and put your PostgreSQL password in it.
4. Load the data (once; re-running resets it):
   `python db.py`
5. Start the app:
   `python app.py`

## Try these vehicles
`MH01AB1234` (healthy), `MH02CD5678` (fast charging, runs hot), `MH03EF9012` (declining health),
`MH04GH3456` (excellent habits). All 200 plates appear in the dropdown.

## Health rules used
- SoH >= 90 % Good, 80-90 % Fair, below 80 % Poor
- Thermal alert: peak temperature above 45 C or below 15 C
- Predicted next peak = average of last 5 peaks + 0.5 C
