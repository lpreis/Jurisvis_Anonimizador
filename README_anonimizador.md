# Anonimizador reversivel para textos juridicos

Aplicacao Streamlit para preparar textos juridicos antes de os enviar para uma LLM:

- escrever texto ou carregar ficheiros `.txt`, `.docx` e `.pdf`;
- detetar dados pessoais e identificadores juridicos;
- substituir entidades por tokens reversiveis;
- selecionar texto diretamente no texto base para adicionar entidades manuais com sugestoes;
- enviar texto anonimizado para OpenAI ou Ollama;
- desanonimizar a resposta com base no vault da sessao.

## Estrutura

- `anonimizador.py`: interface Streamlit.
- `anonymizer_core.py`: deteccao, validacao, vault e reversibilidade.
- `document_io.py`: extracao de TXT, DOCX e PDF.
- `llm_client.py`: clientes OpenAI/Ollama e construcao de prompt.
- `text_selector_component/`: componente Streamlit para selecao manual no texto.
- `tests/`: testes de regressao da anonimização.

## Instalacao recomendada

Algumas bibliotecas de NLP podem nao suportar Python 3.14. Se a instalacao falhar, usa Python 3.11 ou 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

### Modelo spaCy

O `requirements.txt` inclui `pt_core_news_sm`, para que o Presidio tambem fique ativo no Streamlit Cloud. Localmente podes instalar um modelo maior para melhorar a deteccao:

```powershell
python -m spacy download pt_core_news_lg
```

A app procura os modelos por esta ordem: `pt_core_news_lg`, `pt_core_news_md`, `pt_core_news_sm`. Se nenhum existir, funciona apenas com regex e validadores locais, mas deteta menos entidades.

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
