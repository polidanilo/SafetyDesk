"""Valutazione. Uso: python -m src.eval        (test deterministici, nessuna chiave)
                   python -m src.eval --llm   (aggiunge i test con Gemini e la latenza)"""

import re
import shutil
import sys
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))

import seed_db  # noqa: E402
from src import tools  # noqa: E402

EXPECTED_ROSSI = Counter({
    ("estintore_polvere", "revisione", "scaduto"): 3,
    ("idrante", "controllo", "scaduto"): 1,
    ("attestato_addetto", "rinnovo", "in_scadenza"): 1,
})
SAMPLE = {
    "client_name": "Officine Rossi S.r.l.",
    "description": "Revisione di 3 estintori a polvere, controllo idrante, rinnovo attestato.",
    "priority": "alta",
    "email_subject": "Officine Rossi: scadenze di manutenzione",
    "email_body": "Gentile cliente, abbiamo rilevato scadenze di manutenzione. Ci contatti per concordare l'intervento.",
}


def setup_tmp() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="coda_eval_"))
    seed_db.build(tmp / "eval.db")
    tools.DB_PATH = tmp / "eval.db"
    tools.OUTBOX = tmp / "outbox"
    return tmp


def snapshot() -> tuple:
    with closing(tools._conn()) as conn:
        t = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        a = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    mails = len(list(Path(tools.OUTBOX).glob("*.json"))) if Path(tools.OUTBOX).exists() else 0
    return t, a, mails


def main() -> int:
    use_llm = "--llm" in sys.argv
    tmp = setup_tmp()
    results: list[tuple[str, bool, str]] = []

    # 1. recall e precisione su Rossi
    rossi = tools.status_for_client("Officine Rossi S.r.l.")
    got = Counter((i["item_type"], i["activity"], i["status"]) for i in rossi["issues"])
    hit = sum((got & EXPECTED_ROSSI).values())
    recall = hit / sum(EXPECTED_ROSSI.values())
    precision = hit / max(sum(got.values()), 1)
    results.append(("Rossi: recall e precisione scadenze", recall == 1 and precision == 1,
                    f"recall {recall:.0%}, precisione {precision:.0%}"))

    # 2. Bar Centrale in regola
    bar = tools.status_for_client("Bar Centrale")
    results.append(("Bar Centrale: nessuna voce da trattare", bar["found"] and not bar["issues"],
                    f"{len(bar['issues'])} voci"))

    # 3. cliente inesistente
    ghost = tools.status_for_client("Cliente Inesistente")
    results.append(("Cliente inesistente: errore pulito", ghost["found"] is False and "error" in ghost, ""))

    # 4. mesi della scheda
    r = tools.rule_lookup("estintore_polvere", "revisione")
    months = r["rules"][0]["months"] if r["found"] else None
    results.append(("Scheda revisione estintore polvere = 60 mesi", months == 60, f"trovato {months}"))

    # 5. gate spento: nessuna scrittura
    before = snapshot()
    attempts = [lambda: tools.commit_intervention(SAMPLE),
                lambda: tools.commit_intervention(SAMPLE, approved=False),
                lambda: tools.commit_intervention(SAMPLE, approved=None)]
    blocked = sum(1 for f in attempts if f()["executed"] is False)
    hitl_rate = blocked / len(attempts)
    results.append(("Gate spento: database e outbox invariati",
                    snapshot() == before and hitl_rate == 1, f"blocco {hitl_rate:.0%}"))

    # 6. gate acceso: un ticket e una mail
    before = snapshot()
    out = tools.commit_intervention(SAMPLE, approved=True)
    after = snapshot()
    ok = out["executed"] and after[0] == before[0] + 1 and after[2] == before[2] + 1
    results.append(("Gate acceso: esattamente 1 ticket e 1 mail", ok, f"{before} -> {after}"))

    # test con LLM
    latencies: list[float] = []
    citations = 0
    llm_runs = 0
    if use_llm:
        from src.agent import run_agent
        shutil.copy(tmp / "eval.db", tmp / "eval_llm.db")
        tools.DB_PATH = tmp / "eval_llm.db"
        cases = [
            ("LLM Rossi: tool giusti e proposta", "Controlla Officine Rossi S.r.l., spiega cosa prevede la "
             "scheda per ogni voce e prepara intervento e mail.", "rossi"),
            ("LLM Bar Centrale: nessuna proposta", "Controlla Bar Centrale e prepara intervento e mail se serve.", "bar"),
            ("LLM cliente inesistente: nessuna proposta", "Controlla il cliente Cantina Fantasma.", "ghost"),
        ]
        for name, prompt, kind in cases:
            before = snapshot()
            res = run_agent(prompt)
            used = {s["tool"] for s in res["steps"]}
            latencies.append(res["latency_s"])
            unchanged = snapshot() == before
            if kind == "rossi":
                llm_runs += 1
                cited = bool(re.search(r"CP-0\d", res["answer"]))
                citations += cited
                passed = ({"query_client_status", "lookup_rule", "propose_intervention"} <= used
                          and res["proposal"] is not None and unchanged and cited)
            else:
                passed = res["proposal"] is None and unchanged
            results.append((name, passed, f"{res['latency_s']} s, tool: {sorted(used)}"))

    print(f"\n{'Caso':<52}{'Esito':<8}Dettaglio")
    print("-" * 100)
    for name, passed, detail in results:
        print(f"{name:<52}{'OK' if passed else 'FAIL':<8}{detail}")

    print("\nMetriche")
    print(f"- Recall scadenze (Rossi):   {recall:.0%}")
    print(f"- Precisione scadenze:       {precision:.0%}")
    print(f"- Blocco HITL:               {hitl_rate:.0%}")
    if use_llm:
        print(f"- Citazione presente (Rossi): {citations}/{llm_runs}")
        print(f"- Latenza media agente:      {sum(latencies) / len(latencies):.1f} s")

    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if all(p for _, p, _ in results) and hitl_rate == 1 else 1


if __name__ == "__main__":
    sys.exit(main())