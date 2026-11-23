"""Agente: cicla sui tool di lettura e prepara una proposta. Non scrive mai nel database."""

import json
import os
import sys
import time
from datetime import date

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src import tools

load_dotenv()

AGENT_TOOLS = [
    tools.query_client_status,
    tools.list_due,
    tools.lookup_rule,
    tools.search_procedures,
    tools.propose_intervention,
]
TOOLS_BY_NAME = {t.name: t for t in AGENT_TOOLS}

SYSTEM_PROMPT = """Sei SafetyDesk, assistente dell'ufficio tecnico di un'azienda di manutenzione antincendio.
Oggi è {today}. Rispondi sempre in italiano, in modo chiaro e breve.

Regole:
1. Per i dati di un cliente usa SEMPRE query_client_status. Non calcolare né inventare scadenze: gli stati
   (scaduto, in_scadenza, ok) sono già calcolati dal sistema.
2. Per le periodicità usa lookup_rule e cita la fonte tra parentesi quadre, es. [Scheda demo CP-01].
3. Per il formato di ticket e mail puoi usare search_procedures.
4. Se il cliente non esiste, dillo e non proporre nulla.
5. Se non ci sono voci scadute o in scadenza, dillo chiaramente e NON chiamare propose_intervention.
6. Se ci sono voci da trattare, chiama propose_intervention UNA sola volta: priorità = la più alta tra le voci,
   descrizione con tutte le voci e le date, mail formale al cliente con l'elenco.
7. Non dire mai che ticket o mail sono stati creati o inviati: sono bozze in attesa di approvazione umana.
"""


def _text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def _llm() -> ChatGoogleGenerativeAI:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Manca GEMINI_API_KEY in .env")
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite"),
        google_api_key=key,
        max_retries=5,
        temperature=0,
    )


def run_agent(user_text: str, max_steps: int = 8) -> dict:
    start = time.perf_counter()
    llm = _llm().bind_tools(AGENT_TOOLS)
    messages = [SystemMessage(SYSTEM_PROMPT.format(today=date.today().isoformat())),
                HumanMessage(user_text)]
    steps: list[dict] = []
    proposal = None
    answer = ""

    for _ in range(max_steps):
        ai = llm.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            answer = _text(ai.content)
            break
        for call in ai.tool_calls:
            name, args = call["name"], call["args"]
            try:
                result = TOOLS_BY_NAME[name].invoke(args)
            except Exception as exc:  # errore restituito al modello, non fatale
                result = {"error": f"{type(exc).__name__}: {exc}"}
            steps.append({"tool": name, "args": args, "result": result})
            if name == "propose_intervention" and isinstance(result, dict) and result.get("status") == "in_attesa":
                proposal = result["proposal"]
            messages.append(ToolMessage(
                content=json.dumps(result, ensure_ascii=False, default=str),
                tool_call_id=call["id"], name=name))
    else:
        answer = "Limite di passaggi raggiunto senza risposta finale."

    sources: list[str] = []
    for s in steps:
        r = s["result"]
        if s["tool"] == "lookup_rule" and isinstance(r, dict):
            sources += [x["source"] for x in r.get("rules", [])]
        elif s["tool"] == "search_procedures" and isinstance(r, dict):
            sources += [x["source"] for x in r.get("results", [])]
        elif s["tool"] == "query_client_status" and isinstance(r, dict):
            sources += [i["source"] for i in r.get("issues", [])]

    return {
        "answer": answer,
        "steps": steps,
        "proposal": proposal,
        "status": "in_attesa" if proposal else "nessuna_azione",
        "sources": list(dict.fromkeys(sources)),
        "latency_s": round(time.perf_counter() - start, 2),
    }


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or "Controlla la situazione di Officine Rossi S.r.l."
    out = run_agent(prompt)
    print("\n=== RISPOSTA ===\n" + out["answer"])
    print("\n=== PASSAGGI ===")
    for s in out["steps"]:
        print("-", s["tool"], json.dumps(s["args"], ensure_ascii=False))
    print("\n=== STATO ===", out["status"])
    if out["proposal"]:
        p = out["proposal"]
        print(f"TICKET [{p['priority']}] {p['description']}")
        print(f"MAIL: {p['email_subject']}\n{p['email_body']}")
    print(f"\nLatenza: {out['latency_s']} s")