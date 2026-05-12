# Anonimizador reversivel para textos juridicos

Aplicacao Streamlit para preparar textos juridicos antes de os enviar para uma LLM:

- escrever texto ou carregar ficheiros `.txt`, `.docx` e `.pdf`;
- detetar dados pessoais e identificadores juridicos;
- substituir entidades por tokens reversiveis;
- enviar texto anonimizado para OpenAI ou Ollama;
- desanonimizar a resposta com base no vault da sessao.

## Estrutura

- `anonimizador.py`: interface Streamlit.
- `anonymizer_core.py`: deteccao, validacao, vault e reversibilidade.
- `document_io.py`: extracao de TXT, DOCX e PDF.
- `llm_client.py`: clientes OpenAI/Ollama e construcao de prompt.
- `tests/`: testes de regressao da anonimização.

## Instalacao recomendada

Algumas bibliotecas de NLP podem nao suportar Python 3.14. Se a instalacao falhar, usa Python 3.11 ou 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

### Modelo spaCy opcional

Para melhor deteccao de entidades, instala o modelo portugues:

```powershell
python -m spacy download pt_core_news_lg
```

A app funciona sem esse modelo, usando regex e validadores locais.

## Executar

```powershell
streamlit run anonimizador.py
```

## Testes

```powershell
python -m unittest
```

## Notas de seguranca

O vault atual vive apenas na sessao da app. O vault so e mostrado quando a opcao de privacidade correspondente esta ativa. Para producao, guarda o mapa token -> valor original de forma cifrada, com TTL curto, controlo de acesso e sem logs de texto original ou prompts completos.
