# SafetyDesk

Agente AI per la gestione della coda scadenze di un ufficio tecnico antincendio.  
*Progetto dimostrativo di portfolio con dati e schede sintetici.*

L'operatore consulta la coda clienti o interroga l'agente in italiano (es. *"Controlla Officine Rossi, dimmi cosa è scaduto, cosa prevede la scheda di manutenzione e prepara intervento e mail"*). L'agente interroga il registro clienti (estintori, idranti, attestati), recupera le schede di periodicità e le procedure interne tramite RAG, classifica la priorità e prepara una bozza di ticket e di email. **Senza un clic esplicito su Approva da parte dell'operatore, non viene scritta alcuna riga nel database né generata alcuna email.**

**Video demo:** [Guarda su YouTube](https://youtu.be/uBZWgq4ZJoo)

---

## Flusso operativo

```text
Operatore (Streamlit)
  │
  ▼
Agente AI (LangChain + Gemini)
  ├──► query_client_status / list_due   ──► SQLite + rules_engine.py (calcolo deterministico delle date)
  ├──► lookup_rule                      ──► Tabella rules (periodicità e fonte)
  ├──► search_procedures                ──► ChromaDB locale (RAG su procedure markdown)
  └──► propose_intervention             ──► Genera solo una bozza di ticket ed email
  │
  ▼
Gate Human-in-the-Loop
  ├── [Rifiuta] ──► Registra solo audit log ("rifiutato"), database invariato
  └── [Approva] ──► commit_intervention(approved=True) ──► Ticket DB + Email in outbox/ + Audit log
```

---

## Cos'è il RAG e come viene usato qui

Il **RAG (Retrieval-Augmented Generation)** è un'architettura che permette a un modello linguistico (LLM) di cercare informazioni all'interno di documenti esterni prima di formulare una risposta, invece di affidarsi soltanto alla propria memoria di addestramento. Questo riduce drasticamente le allucinazioni e consente di aggiornare le regole aziendali senza riaddestrare il modello.

In **SafetyDesk**, il RAG è implementato in locale con **ChromaDB**:
* I documenti di procedura in `data/docs/` (criteri di priorità dei ticket, tono e struttura delle email ai clienti) vengono suddivisi per sezione e indicizzati tramite un modello di embedding locale (`all-MiniLM-L6-v2` via ONNX, senza chiamate API aggiuntive).
* Quando l'agente deve preparare un intervento, richiama il tool `search_procedures`, che recupera per **similarità semantica** i paragrafi più pertinenti insieme al nome del file e della sezione.
* L'agente usa questi estratti per redigere ticket ed email conformi alle procedure interne, citando sempre la fonte utilizzata.

---

## Stack tecnico

| Componente | Tecnologia | Ruolo |
| :--- | :--- | :--- |
| Dati e calcolo scadenze | Python + SQLite (`rules_engine.py`) | Fonte di verità deterministica: l'LLM non somma mai le date. |
| RAG procedure interne | ChromaDB (locale, embedding ONNX) | Ricerca semantica sui documenti markdown di procedura con citazione di file e sezione. |
| Orchestrazione agente | Python + LangChain (tool calling) | Ciclo multi-step sui soli tool di lettura e proposta. |
| Modello LLM | Gemini Flash (`gemini-3.5-flash-lite`) | Tool calling e sintesi in italiano via API. |
| Gate Human-in-the-Loop | Codice Python (`commit_intervention`) | Separazione strutturale: l'agente non ha accesso ai tool di scrittura. |
| Interfaccia | Streamlit | Coda clienti a semaforo, chat, pannello passaggi/fonti, anteprima e pulsanti Approva/Rifiuta. |
| Valutazione | `src/eval.py` | Suite automatica deterministica + end-to-end con LLM. |

---

## Avvio in locale

1. Crea l'ambiente virtuale e installa le dipendenze:

```bash
python -m venv .venv
.venv\Scripts\activate        # Su Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

2. Copia `.env.example` in `.env` e inserisci la tua `GEMINI_API_KEY` (e opzionalmente `GEMINI_MODEL`).

3. Popola il database demo (date ancorate a oggi):

```bash
python data/seed_db.py
```

4. Avvia l'interfaccia Streamlit:

```bash
streamlit run app.py
```

> *Nota: al primo avvio ChromaDB scarica automaticamente in locale il modello di embedding `all-MiniLM-L6-v2` (circa 80 MB), che resta poi in cache.*

---

## Valutazione e metriche

La suite di test verifica sia la logica deterministica (zero chiamate API) sia il comportamento end-to-end dell'agente:

```bash
python -m src.eval        # Test deterministici (6 casi)
python -m src.eval --llm  # Suite completa con agente LLM (9 casi)
```

### Risultati (`python -m src.eval --llm` — 9/9 OK)

| Metrica | Risultato | Note |
| :--- | :--- | :--- |
| **Recall scadenze (Officine Rossi)** | **100%** | 5/5 voci rilevate (3 revisioni estintori, 1 controllo idrante, 1 attestato in scadenza) |
| **Precisione scadenze** | **100%** | 0 falsi interventi su cliente in regola (Bar Centrale) e cliente inesistente |
| **Blocco Human-in-the-Loop (HITL)** | **100%** | Con `approved=False` DB e `outbox/` restano invariati; con `approved=True` esattamente 1 ticket e 1 mail |
| **Citazione fonte presente (Rossi)** | **1/1** | Periodicità corrette (es. 60 mesi revisione polvere) con etichetta fonte |
| **Latenza media agente** | **22.4 s** | Rossi: 56.67 s · Bar Centrale: 2.77 s · Cliente inesistente: 7.90 s |
