"""Interfaccia Streamlit di CodaPresidi. Avvio: streamlit run app.py"""

import json

import streamlit as st

from src import tools
from src.agent import run_agent

st.set_page_config(page_title="CodaPresidi", layout="wide")

DEFAULT_PROMPT = (
    "Controlla la situazione del cliente Officine Rossi S.r.l., dimmi quali presidi sono scaduti, "
    "cosa prevede la scheda di manutenzione per ciascuno e prepara l'intervento e la mail di avviso."
)
ICONS = {"rosso": "🔴", "giallo": "🟡", "verde": "🟢"}

st.session_state.setdefault("result", None)
st.session_state.setdefault("notice", None)

# ---- sinistra: coda scadenze ----
with st.sidebar:
    st.header("Coda scadenze")
    for row in tools.due_queue():
        st.markdown(f"{ICONS[row['livello']]} **{row['client']}**  \n"
                    f"{row['scaduti']} scadute · {row['in_scadenza']} in scadenza")
    st.caption("Dati inventati a scopo dimostrativo. Le date sono calcolate dal codice, non dal modello.")

st.title("CodaPresidi")

col_main, col_trace = st.columns([3, 2])

# ---- centro: richiesta e risposta ----
with col_main:
    prompt = st.text_area("Richiesta all'agente", value=DEFAULT_PROMPT, height=130)
    if st.button("Chiedi all'agente", type="primary"):
        st.session_state.notice = None
        with st.spinner("L'agente sta lavorando..."):
            try:
                st.session_state.result = run_agent(prompt)
            except Exception as exc:
                st.session_state.result = None
                st.error(f"Errore: {exc}")
    result = st.session_state.result
    if result:
        st.subheader("Risposta")
        st.write(result["answer"])
        st.caption(f"Latenza: {result['latency_s']} s · Stato: {result['status']}")

# ---- destra: passaggi e fonti ----
with col_trace:
    result = st.session_state.result
    with st.expander("Passaggi dell'agente e fonti", expanded=True):
        if result:
            for i, step in enumerate(result["steps"], 1):
                st.markdown(f"**{i}. `{step['tool']}`**")
                st.code(json.dumps(step["args"], ensure_ascii=False, indent=2), language="json")
            st.markdown("**Fonti citate**")
            for s in result["sources"] or ["nessuna"]:
                st.markdown(f"- {s}")
        else:
            st.write("Nessuna richiesta eseguita.")

# ---- basso: anteprima e approvazione ----
result = st.session_state.result
if result and result["proposal"]:
    p = result["proposal"]
    st.divider()
    st.subheader("Anteprima: richiede approvazione")
    st.warning("Nulla è stato scritto. Ticket e mail partono solo dopo Approva.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Ticket** · cliente: {p['client_name']} · priorità: **{p['priority']}**")
        st.write(p["description"])
    with c2:
        st.markdown(f"**Mail** · oggetto: {p['email_subject']}")
        st.text(p["email_body"])
    b1, b2 = st.columns(2)
    if b1.button("Approva", type="primary"):
        out = tools.commit_intervention(p, approved=True)
        st.session_state.notice = (f"Ticket #{out['ticket_id']} creato, mail salvata in {out['email_file']}"
                                   if out["executed"] else f"Non eseguito: {out['reason']}")
        st.session_state.result["proposal"] = None
        st.rerun()
    if b2.button("Rifiuta"):
        tools.reject_intervention(p)
        st.session_state.notice = "Proposta rifiutata. Nessun ticket creato, registrato solo l'audit."
        st.session_state.result["proposal"] = None
        st.rerun()

if st.session_state.notice:
    st.success(st.session_state.notice)

st.divider()
t1, t2 = st.columns(2)
with t1:
    st.subheader("Ticket")
    st.dataframe(tools.recent_tickets(), use_container_width=True)
with t2:
    st.subheader("Log di audit")
    st.dataframe(tools.recent_audit(), use_container_width=True)