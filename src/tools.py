"""Tool dell'agente. Lettura libera, scrittura solo con approvazione esplicita."""

import json
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.rules_engine import evaluate, priority_for

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "coda_presidi.db"
DOCS_DIR = ROOT / "data" / "docs"
OUTBOX = ROOT / "outbox"

ACTIVITY_COLUMN = {"controllo": "last_check", "revisione": "last_revision"}
STATUS_ORDER = {"scaduto": 0, "in_scadenza": 1, "ok": 2}


# ---------- accesso al database ----------

def _conn() -> sqlite3.Connection:
    if not Path(DB_PATH).exists():
        raise FileNotFoundError("Database mancante: lancia prima python data/seed_db.py")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _find_client(conn: sqlite3.Connection, name: str):
    row = conn.execute("SELECT * FROM clients WHERE lower(name) = lower(?)", (name.strip(),)).fetchone()
    if row:
        return row
    return conn.execute(
        "SELECT * FROM clients WHERE lower(name) LIKE lower(?) ORDER BY name LIMIT 1",
        (f"%{name.strip()}%",),
    ).fetchone()


def _client_items(conn: sqlite3.Connection, client_id: int, warn_days: int = 30) -> list[dict]:
    """Tutte le voci del cliente con stato calcolato in codice."""
    rules = {(r["asset_type"], r["activity"]): r for r in conn.execute("SELECT * FROM rules")}
    items: list[dict] = []

    for a in conn.execute("SELECT * FROM assets WHERE client_id = ?", (client_id,)):
        for (asset_type, activity), rule in rules.items():
            if asset_type != a["asset_type"] or activity not in ACTIVITY_COLUMN:
                continue
            last_s = a[ACTIVITY_COLUMN[activity]]
            ev = evaluate(date.fromisoformat(last_s) if last_s else None, rule["months"], warn_days=warn_days)
            items.append({
                "item_type": a["asset_type"], "label": a["label"], "activity": activity,
                "last_date": last_s, "due_date": ev["due_date"], "days_left": ev["days_left"],
                "status": ev["status"], "priority": priority_for(activity, ev["status"]),
                "months_rule": rule["months"], "source": rule["source"],
            })

    for c in conn.execute("SELECT * FROM certificates WHERE client_id = ?", (client_id,)):
        rule = rules.get((c["cert_type"], "rinnovo"))
        if not rule:
            continue
        ev = evaluate(date.fromisoformat(c["issued_date"]) if c["issued_date"] else None,
                      rule["months"], warn_days=warn_days)
        items.append({
            "item_type": c["cert_type"], "label": f"Attestato addetto antincendio - {c['holder']}",
            "activity": "rinnovo", "last_date": c["issued_date"], "due_date": ev["due_date"],
            "days_left": ev["days_left"], "status": ev["status"],
            "priority": priority_for("rinnovo", ev["status"]),
            "months_rule": rule["months"], "source": rule["source"],
        })
    return items


# ---------- funzioni di lettura ----------

def status_for_client(client_name: str, warn_days: int = 30) -> dict:
    with closing(_conn()) as conn:
        client = _find_client(conn, client_name)
        if client is None:
            return {"found": False, "error": f"Cliente '{client_name}' non presente nel registro."}
        items = _client_items(conn, client["id"], warn_days)
    issues = sorted((i for i in items if i["status"] != "ok"),
                    key=lambda i: (STATUS_ORDER[i["status"]], i["days_left"] if i["days_left"] is not None else -9999))
    return {
        "found": True,
        "client": {"id": client["id"], "name": client["name"], "email": client["email"]},
        "today": date.today().isoformat(),
        "items_checked": len(items),
        "items_ok": len(items) - len(issues),
        "issues": issues,
    }


def due_queue(warn_days: int = 30) -> list[dict]:
    rows = []
    with closing(_conn()) as conn:
        for client in conn.execute("SELECT * FROM clients ORDER BY name"):
            items = _client_items(conn, client["id"], warn_days)
            expired = sum(1 for i in items if i["status"] == "scaduto")
            expiring = sum(1 for i in items if i["status"] == "in_scadenza")
            level = "rosso" if expired else ("giallo" if expiring else "verde")
            rows.append({"client": client["name"], "scaduti": expired,
                         "in_scadenza": expiring, "livello": level})
    order = {"rosso": 0, "giallo": 1, "verde": 2}
    return sorted(rows, key=lambda r: order[r["livello"]])


def rule_lookup(asset_type: str, activity: str | None = None) -> dict:
    query = "SELECT asset_type, activity, months, source, note FROM rules WHERE asset_type = ?"
    params: list = [asset_type.strip().lower()]
    if activity:
        query += " AND activity = ?"
        params.append(activity.strip().lower())
    with closing(_conn()) as conn:
        rows = [dict(r) for r in conn.execute(query, params)]
    if not rows:
        return {"found": False, "error": f"Nessuna scheda per '{asset_type}'."}
    return {"found": True, "rules": rows}


def _sections() -> list[dict]:
    out = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        title, buf = None, []
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                if title:
                    out.append({"source": f"{f.name} > {title}", "text": "\n".join(buf).strip()})
                title, buf = line[3:].strip(), []
            elif title:
                buf.append(line)
        if title:
            out.append({"source": f"{f.name} > {title}", "text": "\n".join(buf).strip()})
    return out


def procedure_search(query: str) -> dict:
    words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 3}
    scored = []
    for s in _sections():
        haystack = (s["source"] + " " + s["text"]).lower()
        score = sum(1 for w in words if w in haystack)
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return {"results": [s for _, s in scored[:2]]}


# ---------- proposta e scrittura ----------

class Proposal(BaseModel):
    client_name: str = Field(description="Nome del cliente, come restituito da query_client_status")
    description: str = Field(min_length=10, description="Descrizione del ticket: voci, scadenze, attività richiesta")
    priority: Literal["alta", "media", "bassa"] = Field(description="Priorità del ticket")
    email_subject: str = Field(min_length=3, description="Oggetto della mail al cliente")
    email_body: str = Field(min_length=20, description="Corpo della mail in italiano formale")


def commit_intervention(proposal: dict, approved: bool = False) -> dict:
    """Unica funzione che scrive ticket e mail. Senza approved=True non tocca nulla."""
    if approved is not True:
        return {"executed": False, "reason": "Approvazione umana mancante: nessuna scrittura."}
    p = Proposal(**proposal)
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_conn()) as conn:
        client = _find_client(conn, p.client_name)
        if client is None:
            return {"executed": False, "reason": "Cliente non trovato: nessuna scrittura."}
        cur = conn.execute(
            "INSERT INTO tickets (client_id, description, priority, status, created_at) "
            "VALUES (?,?,?,?,?)",
            (client["id"], p.description, p.priority, "aperto", now),
        )
        ticket_id = cur.lastrowid
        conn.execute(
            "INSERT INTO audit_log (ts, action, client_id, detail) VALUES (?,?,?,?)",
            (now, "approvato", client["id"], f"ticket #{ticket_id}; mail a {client['email']}"),
        )
        conn.commit()
        recipient = client["email"]
    OUTBOX.mkdir(parents=True, exist_ok=True)
    mail_path = Path(OUTBOX) / f"{datetime.now():%Y%m%d_%H%M%S}_ticket{ticket_id}.json"
    mail_path.write_text(
        json.dumps({"to": recipient, "subject": p.email_subject, "body": p.email_body,
                    "ticket_id": ticket_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"executed": True, "ticket_id": ticket_id, "email_file": str(mail_path)}


def reject_intervention(proposal: dict) -> dict:
    """Rifiuto: scrive solo la riga di audit, nessun ticket e nessuna mail."""
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_conn()) as conn:
        client = _find_client(conn, proposal.get("client_name", ""))
        conn.execute(
            "INSERT INTO audit_log (ts, action, client_id, detail) VALUES (?,?,?,?)",
            (now, "rifiutato", client["id"] if client else None, "proposta rifiutata dall'operatore"),
        )
        conn.commit()
    return {"executed": False, "reason": "Proposta rifiutata."}


def recent_audit(limit: int = 10) -> list[dict]:
    with closing(_conn()) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, ts, action, client_id, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


def recent_tickets(limit: int = 10) -> list[dict]:
    with closing(_conn()) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, client_id, priority, status, created_at, description "
            "FROM tickets ORDER BY id DESC LIMIT ?", (limit,))]


# ---------- tool esposti al modello (nessuno scrive) ----------

@tool
def query_client_status(client_name: str) -> dict:
    """Legge dal registro i presidi e gli attestati di un cliente. Restituisce solo le voci scadute o in
    scadenza (stato già calcolato dal sistema), con la fonte della scheda. Usalo sempre per i dati."""
    return status_for_client(client_name)


@tool
def list_due() -> list:
    """Elenca tutti i clienti con numero di voci scadute e in scadenza (coda di lavoro)."""
    return due_queue()


@tool
def lookup_rule(asset_type: str, activity: str = "") -> dict:
    """Cerca la scheda di periodicità per un tipo di presidio (es. estintore_polvere, idrante,
    attestato_addetto) e un'attività (controllo, revisione, rinnovo). Restituisce mesi e fonte."""
    return rule_lookup(asset_type, activity or None)


@tool
def search_procedures(query: str) -> dict:
    """Cerca nelle procedure interne (apertura intervento, mail al cliente) le sezioni pertinenti."""
    return procedure_search(query)


@tool(args_schema=Proposal)
def propose_intervention(client_name: str, description: str, priority: str,
                         email_subject: str, email_body: str) -> dict:
    """Prepara la BOZZA di ticket e mail per un cliente. Non scrive nulla: resta in attesa di
    approvazione umana. Chiamalo una sola volta, solo se ci sono voci scadute o in scadenza."""
    with closing(_conn()) as conn:
        if _find_client(conn, client_name) is None:
            return {"status": "errore", "error": f"Cliente '{client_name}' non presente nel registro."}
    return {"status": "in_attesa", "message": "Bozza registrata, in attesa di approvazione umana.",
            "proposal": {"client_name": client_name, "description": description, "priority": priority,
                         "email_subject": email_subject, "email_body": email_body}}