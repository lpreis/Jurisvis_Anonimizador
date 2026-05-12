# Anonimizador reversível para LLM

Aplicação Streamlit para:

- escrever texto ou carregar ficheiros `.txt`, `.docx` e `.pdf`;
- detetar dados pessoais e substituir por tokens reversíveis;
- enviar o texto original ou anonimizado para uma LLM;
- desanonimizar a resposta com base no vault da sessão.

## Instalação recomendada

Algumas bibliotecas de NLP podem não suportar Python 3.14. Se a instalação falhar, usa Python 3.11 ou 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
python -m spacy download pt_core_news_lg
```

## Executar

```powershell
streamlit run anonimizador.py
```

## LLMs suportadas

- OpenAI: coloca a chave na barra lateral ou define `OPENAI_API_KEY`.
- Ollama: usa uma instância local, por exemplo `http://localhost:11434`, e escolhe o modelo.

## Notas de segurança

O vault atual vive apenas na sessão da app. Para produção, guarda o mapa token -> valor original de forma cifrada, com TTL curto, sem logs de texto original ou prompts completos.
