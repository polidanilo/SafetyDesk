# CodaPresidi

Agente AI per la coda scadenze di un ufficio tecnico antincendio. Progetto dimostrativo con dati
inventati, non affiliato a Wedoot / 626 Antincendi.

L'agente legge un registro clienti (estintori, idranti, attestati), recupera la scheda di periodicità con la
fonte, prepara ticket e mail e si ferma: senza Approva non viene scritto nulla.

**Le date di scadenza le calcola il codice, non il modello.** Il modello sceglie i tool e scrive l'italiano.

## Flusso
operatore -> agente -> [query_client_status, lookup_rule, search_procedures] -> propose_intervention
-> anteprima -> Approva / Rifiuta -> commit_intervention -> ticket + mail in outbox + audit log

## Avvio
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copia .env.example in .env e inserisci GEMINI_API_KEY
python data/seed_db.py
streamlit run app.py

## Valutazione
python -m src.eval --llm

| Metrica | Risultato |
|---|---|
| Recall scadenze (Rossi) | ... |
| Precisione | ... |
| Blocco HITL | ... |
| Citazione presente | ... |
| Latenza media | ... |

## Limiti
Schede e documenti sono sintetici e vanno validati da un tecnico. Il registro è SQLite; in produzione lo
stesso gate può stare davanti al CRM aziendale.