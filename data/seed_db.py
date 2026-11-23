"""Crea il database demo (dati inventati). Uso: python data/seed_db.py"""

import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rules_engine import add_months  # noqa: E402

DEFAULT_DB = ROOT / "coda_presidi.db"

SCHEMA = """
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS rules;
DROP TABLE IF EXISTS certificates;
DROP TABLE IF EXISTS assets;
DROP TABLE IF EXISTS clients;

CREATE TABLE clients (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    city TEXT
);
CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    asset_type TEXT NOT NULL,
    label TEXT NOT NULL,
    last_check TEXT,
    last_revision TEXT
);
CREATE TABLE certificates (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    cert_type TEXT NOT NULL,
    holder TEXT NOT NULL,
    issued_date TEXT
);
CREATE TABLE rules (
    id INTEGER PRIMARY KEY,
    asset_type TEXT NOT NULL,
    activity TEXT NOT NULL,
    months INTEGER NOT NULL,
    source TEXT NOT NULL,
    note TEXT
);
CREATE TABLE tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    description TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aperto',
    created_at TEXT NOT NULL
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    client_id INTEGER,
    detail TEXT
);
"""

SRC_ESTINTORI = "Scheda demo CP-01 (cadenze da sintesi UNI 9994-1:2024, da confermare con un tecnico)"
SRC_IDRANTI = "Scheda demo CP-02 (rif. UNI 10779 / UNI EN 671, da confermare con un tecnico)"
SRC_ATTESTATI = "Scheda demo CP-03 (formazione addetti antincendio, da confermare con un tecnico)"

RULES = [
    ("estintore_polvere", "controllo", 6, SRC_ESTINTORI, "Controllo periodico semestrale"),
    ("estintore_polvere", "revisione", 60, SRC_ESTINTORI, "Revisione a 60 mesi"),
    ("estintore_co2", "controllo", 6, SRC_ESTINTORI, "Controllo periodico semestrale"),
    ("estintore_co2", "revisione", 60, SRC_ESTINTORI, "Revisione a 60 mesi"),
    ("idrante", "controllo", 6, SRC_IDRANTI, "Controllo almeno semestrale"),
    ("attestato_addetto", "rinnovo", 60, SRC_ATTESTATI, "Rinnovo dopo 5 anni (scheda demo)"),
]


def build(db_path: Path = DEFAULT_DB) -> None:
    today = date.today()

    def ago(months: int, extra_days: int = 0) -> str:
        return (add_months(today, -months) + timedelta(days=extra_days)).isoformat()

    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO rules (asset_type, activity, months, source, note) VALUES (?,?,?,?,?)",
            RULES,
        )
        conn.executemany(
            "INSERT INTO clients (id, name, email, city) VALUES (?,?,?,?)",
            [
                (1, "Officine Rossi S.r.l.", "ufficio@officinerossi.example", "Ferrara"),
                (2, "Bar Centrale", "info@barcentrale.example", "Ferrara"),
                (3, "Pasticceria Bianchi", "ordini@pasticceriabianchi.example", "Ferrara"),
            ],
        )
        assets = [
            # Officine Rossi: 3 revisioni scadute + 1 controllo idrante scaduto
            (1, "estintore_polvere", "Estintore polvere 6 kg - Reparto A", ago(2), ago(66)),
            (1, "estintore_polvere", "Estintore polvere 6 kg - Reparto B", ago(2), ago(63)),
            (1, "estintore_polvere", "Estintore polvere 6 kg - Magazzino", ago(2), ago(61)),
            (1, "estintore_co2", "Estintore CO2 5 kg - Quadro elettrico", ago(2), ago(20)),
            (1, "idrante", "Idrante a muro - Cortile", ago(8), None),
            # Bar Centrale: tutto in regola
            (2, "estintore_polvere", "Estintore polvere 6 kg - Sala", ago(2), ago(20)),
            (2, "estintore_polvere", "Estintore polvere 6 kg - Cucina", ago(3), ago(30)),
            (2, "idrante", "Idrante a muro - Ingresso", ago(3), None),
            # Pasticceria Bianchi: un solo controllo in scadenza tra 15 giorni
            (3, "estintore_polvere", "Estintore polvere 6 kg - Laboratorio", ago(6, 15), ago(10)),
            (3, "estintore_polvere", "Estintore polvere 6 kg - Negozio", ago(1), ago(40)),
        ]
        conn.executemany(
            "INSERT INTO assets (client_id, asset_type, label, last_check, last_revision) "
            "VALUES (?,?,?,?,?)",
            assets,
        )
        conn.executemany(
            "INSERT INTO certificates (client_id, cert_type, holder, issued_date) VALUES (?,?,?,?)",
            [
                (1, "attestato_addetto", "Marco Verdi", ago(60, 10)),  # scade tra 10 giorni
                (2, "attestato_addetto", "Giulia Neri", ago(24)),
                (3, "attestato_addetto", "Paolo Gialli", ago(12)),
            ],
        )
        conn.commit()


if __name__ == "__main__":
    build()
    print(f"Database creato: {DEFAULT_DB}")