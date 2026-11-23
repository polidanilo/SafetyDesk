"""Chiede a Gemini di chiamare il tool finto ping e stampa gli argomenti."""

import os
import sys

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()


@tool
def ping(message: str) -> str:
    """Echo di controllo. Va chiamato una sola volta."""
    return message


def main() -> None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit("Manca GEMINI_API_KEY in .env")
    model = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        google_api_key=key,
    )
    response = model.bind_tools([ping], tool_choice="ping").invoke(
        "Chiama il tool ping con message uguale a coda-presidi."
    )
    if not response.tool_calls:
        sys.exit(f"Nessun tool chiamato. Contenuto: {response.content!r}")
    print(response.tool_calls[0]["args"])


if __name__ == "__main__":
    main()
