"""RAG sulle procedure: indicizza i markdown di data/docs per sezione (##) in Chroma."""

import hashlib
import re
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "data" / "docs"
CHROMA_PATH = ROOT / "chroma_db"  # percorso assoluto: non dipende dalla cartella da cui lanci
COLLECTION_NAME = "procedure"

_client = None
_collection = None


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_sections() -> list[dict]:
    """Divide ogni .md di data/docs in sezioni '## Titolo'. Il testo prima del primo '##' è ignorato."""
    sections: list[dict] = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        title, buf = None, []

        def flush():
            text = "\n".join(buf).strip()
            if title and text:
                sections.append({"source": f"{f.name} > {title}", "title": title, "text": text})

        for line in f.read_text(encoding="utf-8").splitlines():
            if re.match(r"^##\s+", line):
                flush()
                title, buf = line[2:].strip(), []
            elif title:
                buf.append(line)
        flush()
    return sections


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        )
    return _collection


def _sync(col) -> None:
    """Allinea l'indice ai file: aggiunge/aggiorna le sezioni cambiate, rimuove quelle sparite."""
    want = {_sha(s["source"]): {**s, "hash": _sha(s["title"] + "\n" + s["text"])} for s in load_sections()}
    existing = col.get(include=["metadatas"])
    have = {i: (m or {}).get("hash") for i, m in zip(existing["ids"], existing["metadatas"])}

    stale = [i for i in have if i not in want]
    if stale:
        col.delete(ids=stale)

    changed = [i for i, s in want.items() if have.get(i) != s["hash"]]
    if changed:
        col.upsert(
            ids=changed,
            # il titolo entra nell'embedding: aiuta query come "priorità del ticket"
            documents=[f"{want[i]['title']}\n{want[i]['text']}" for i in changed],
            metadatas=[{"source": want[i]["source"], "content": want[i]["text"], "hash": want[i]["hash"]}
                       for i in changed],
        )


def search_docs(query: str, k: int = 3) -> list[dict]:
    """Ricerca semantica sulle sezioni. Restituisce [{"source": ..., "content": ...}]."""
    if not query or not query.strip():
        return []
    col = _get_collection()
    _sync(col)
    n = min(k, col.count())
    if n == 0:
        return []
    res = col.query(query_texts=[query], n_results=n, include=["metadatas"])
    return [{"source": m["source"], "content": m["content"]} for m in res["metadatas"][0]]


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "quale priorità do al ticket?"
    for r in search_docs(q):
        print(f"- {r['source']}\n  {r['content'][:120]}...")