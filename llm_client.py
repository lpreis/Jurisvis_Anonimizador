from __future__ import annotations

import os


def call_llm(provider: str, prompt: str, model: str, api_key: str, base_url: str) -> str:
    if provider == "OpenAI":
        return call_openai(prompt=prompt, model=model, api_key=api_key)
    if provider == "Ollama":
        return call_ollama(prompt=prompt, model=model, base_url=base_url)
    raise ValueError(f"Fornecedor desconhecido: {provider}")


def call_openai(prompt: str, model: str, api_key: str) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Para usar OpenAI instala: pip install openai") from exc

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Define OPENAI_API_KEY ou introduz a chave na barra lateral.")

    client = OpenAI(api_key=key)
    response = client.responses.create(model=model, input=prompt)
    return response.output_text


def call_ollama(prompt: str, model: str, base_url: str) -> str:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Para usar Ollama instala: pip install requests") from exc

    url = base_url.rstrip("/") + "/api/generate"
    response = requests.post(
        url,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def build_prompt(question: str, text: str, is_anonymized: bool) -> str:
    token_instruction = ""
    if is_anonymized:
        token_instruction = (
            "O texto contem placeholders como [PESSOA_1], [ORGANIZACAO_1] ou [EMAIL_1]. "
            "Mantem todos os placeholders exatamente como estao. "
            "Nao traduzas, nao renomeies e nao inventes placeholders.\n\n"
        )

    return (
        f"{token_instruction}"
        "Responde a pergunta usando apenas a informacao relevante do texto.\n\n"
        f"Pergunta:\n{question.strip()}\n\n"
        f"Texto:\n{text.strip()}"
    )
