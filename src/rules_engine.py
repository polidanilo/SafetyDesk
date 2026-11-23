"""Calcolo delle scadenze. Le date le decide il codice, non il modello."""

import calendar
from datetime import date


def add_months(d: date, months: int) -> date:
    """Somma (o sottrae) mesi a una data, limitando il giorno a fine mese."""
    year_offset, month_index = divmod(d.month - 1 + months, 12)
    year = d.year + year_offset
    month = month_index + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def evaluate(last: date | None, months: int, today: date | None = None,
             warn_days: int = 30) -> dict:
    """Stato di una voce: ok, in_scadenza o scaduto."""
    today = today or date.today()
    if last is None:
        return {"due_date": None, "days_left": None, "status": "scaduto"}
    due = add_months(last, months)
    days_left = (due - today).days
    if days_left < 0:
        status = "scaduto"
    elif days_left <= warn_days:
        status = "in_scadenza"
    else:
        status = "ok"
    return {"due_date": due.isoformat(), "days_left": days_left, "status": status}


def priority_for(activity: str, status: str) -> str:
    """Alta: revisione/rinnovo scaduti. Media: controllo scaduto. Bassa: in scadenza."""
    if status == "scaduto":
        return "alta" if activity in ("revisione", "rinnovo") else "media"
    return "bassa"