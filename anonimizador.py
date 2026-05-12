from __future__ import annotations

import os
import subprocess
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from anonymizer_core import ENTITY_TYPES, EntityMatch, ReversibleAnonymizer
from document_io import extract_text
from llm_client import build_prompt, call_llm


TEXT_SELECTOR = components.declare_component(
    "text_selector",
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "text_selector_component"),
)


def initialize_state() -> None:
    if "anonymizer" not in st.session_state:
        st.session_state.anonymizer = ReversibleAnonymizer(warning_callback=st.warning)
    if "source_text" not in st.session_state:
        st.session_state.source_text = ""
    if "anonymized_text" not in st.session_state:
        st.session_state.anonymized_text = ""
    if "llm_response" not in st.session_state:
        st.session_state.llm_response = ""
    if "deanonymized_response" not in st.session_state:
        st.session_state.deanonymized_response = ""
    if "matches" not in st.session_state:
        st.session_state.matches = []
    if "manual_selection_result" not in st.session_state:
        st.session_state.manual_selection_result = ""
    if "last_selection_nonce" not in st.session_state:
        st.session_state.last_selection_nonce = 0


def get_last_modified_time() -> str:
    try:
        timestamp = os.path.getmtime(__file__)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "desconhecida"


def get_git_version() -> str:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return sha
    except Exception:
        return "desconhecida"


def entity_table(matches: list[EntityMatch]) -> list[dict[str, object]]:
    return [
        {
            "tipo": match.entity_type,
            "valor": match.text,
            "score": round(match.score, 2),
            "origem": match.source,
        }
        for match in matches
    ]


def render_sidebar() -> tuple[str, str, str, str, bool, bool]:
    st.sidebar.header("LLM")
    provider = st.sidebar.selectbox("Fornecedor", ["OpenAI", "Ollama"])

    if provider == "OpenAI":
        model = st.sidebar.text_input("Modelo", value="gpt-4.1-mini")
        api_key = st.sidebar.text_input("OPENAI_API_KEY", type="password", value="")
        base_url = ""
        st.sidebar.caption("Tambem podes definir a variavel de ambiente OPENAI_API_KEY.")
    else:
        model = st.sidebar.text_input("Modelo", value="llama3.1")
        base_url = st.sidebar.text_input("URL Ollama", value="http://localhost:11434")
        api_key = ""

    st.sidebar.header("Privacidade")
    show_vault = st.sidebar.toggle("Mostrar vault da sessao", value=False)
    show_debug = st.sidebar.toggle("Mostrar diagnostico tecnico", value=False)

    st.sidebar.header("Sessao")
    if st.sidebar.button("Limpar vault e respostas"):
        st.session_state.anonymizer.reset()
        st.session_state.anonymized_text = ""
        st.session_state.llm_response = ""
        st.session_state.deanonymized_response = ""
        st.session_state.matches = []
        st.session_state.manual_selection_result = ""
        st.rerun()

    return provider, model, api_key, base_url, show_vault, show_debug


def apply_manual_entity(text_to_anonymize: str, entity_type: str) -> str:
    anonymizer: ReversibleAnonymizer = st.session_state.anonymizer
    base_text = st.session_state.anonymized_text or st.session_state.source_text
    anonymized_text, token = anonymizer.replace_manual_entity(base_text, text_to_anonymize, entity_type)
    st.session_state.anonymized_text = anonymized_text
    st.session_state.manual_selection_result = token
    return token


def render_text_selection_anonymization() -> None:
    st.subheader("Anonimizacao por selecao")
    st.caption("Seleciona uma passagem no texto abaixo e escolhe o tipo de entidade.")

    if not st.session_state.source_text.strip():
        st.info("Insere ou extrai texto base para ativar a selecao manual.")
        return

    selection = TEXT_SELECTOR(
        text=st.session_state.source_text,
        entityTypes=ENTITY_TYPES,
        key="text_selector_component",
        default=None,
    )

    if not selection:
        return

    nonce = int(selection.get("nonce", 0))
    if nonce <= st.session_state.last_selection_nonce:
        return

    selected_text = str(selection.get("text", "")).strip()
    selected_type = str(selection.get("entity_type", "")).strip()
    if not selected_text or selected_type not in ENTITY_TYPES:
        return

    st.session_state.last_selection_nonce = nonce
    token = apply_manual_entity(selected_text, selected_type)
    st.success(f"Selecao anonimizada como {token}")
    st.rerun()


def render_manual_anonymization() -> None:
    st.subheader("Anonimizacao manual")
    st.caption("Alternativa para escrever uma entidade manualmente.")

    text_to_anonymize = st.text_input(
        "Texto exato a anonimizar",
        placeholder="Ex.: Dr. Joao Silva, ABC Lda, 213 884 992",
    )
    if not text_to_anonymize:
        return

    anonymizer: ReversibleAnonymizer = st.session_state.anonymizer
    similar_in_vault = anonymizer.find_similar_in_vault(text_to_anonymize)

    if similar_in_vault:
        st.info("Foram encontradas correspondencias parecidas no vault.")
        selected_idx = st.selectbox(
            "Usar token existente",
            range(len(similar_in_vault)),
            format_func=lambda index: (
                f"{similar_in_vault[index][0]} ({similar_in_vault[index][2] * 100:.0f}% match)"
            ),
        )
        selected_token = similar_in_vault[selected_idx][0]
        if st.button("Usar este token", type="primary"):
            st.session_state.anonymized_text = (st.session_state.anonymized_text or st.session_state.source_text).replace(
                text_to_anonymize,
                selected_token,
            )
            st.session_state.manual_selection_result = selected_token
            st.success(f"Substituido por {selected_token}")
        return

    suggestions = anonymizer.get_entity_suggestions(text_to_anonymize)
    if suggestions:
        option_labels = [f"{entity_type} ({score * 100:.0f}% confianca)" for entity_type, score in suggestions]
        selected_idx = st.radio(
            "Tipo sugerido",
            range(len(suggestions)),
            format_func=lambda index: option_labels[index],
        )
        selected_type = suggestions[selected_idx][0]
    else:
        selected_type = st.selectbox("Tipo de entidade", ENTITY_TYPES)

    if st.button("Anonimizar manualmente", type="primary"):
        token = apply_manual_entity(text_to_anonymize, selected_type)
        st.success(f"Adicionado ao vault como {token}")


def render_detection_report(show_debug: bool) -> None:
    anonymizer: ReversibleAnonymizer = st.session_state.anonymizer
    report = anonymizer.last_report

    if st.session_state.matches:
        st.write(f"Entidades detetadas: {len(st.session_state.matches)}")
        st.dataframe(entity_table(st.session_state.matches), use_container_width=True, hide_index=True)
        counts = report.counts_by_type()
        if counts:
            st.caption("Resumo por tipo: " + ", ".join(f"{key}: {value}" for key, value in counts.items()))
    else:
        st.info("Ainda nao ha entidades detetadas nesta sessao.")

    if show_debug and report.rejected:
        with st.expander("Candidatos rejeitados por conflito"):
            st.dataframe(entity_table(report.rejected), use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Anonimizador LLM", page_icon="lock", layout="wide")
    initialize_state()
    provider, model, api_key, base_url, show_vault, show_debug = render_sidebar()

    st.title("Anonimizador reversivel para textos juridicos")
    st.caption(f"Ultima alteracao do codigo: {get_last_modified_time()} | Versao: {get_git_version()}")

    if show_debug:
        analyzer = st.session_state.anonymizer.presidio_analyzer
        model_name = st.session_state.anonymizer.presidio_model_name or "sem modelo spaCy"
        st.info(f"Presidio ativo: {analyzer is not None} | Modelo NLP: {model_name}")

    upload_col, text_col = st.columns([0.9, 1.1], gap="large")
    with upload_col:
        uploaded_file = st.file_uploader("Documento TXT, DOCX ou PDF", type=["txt", "docx", "pdf"])
        if uploaded_file is not None and st.button("Extrair texto do documento"):
            try:
                st.session_state.source_text = extract_text(uploaded_file)
            except Exception as exc:
                st.error(str(exc))

        language = st.selectbox("Idioma de deteccao", ["pt"], index=0)
        use_anonymized = st.toggle("Enviar texto anonimizado para a LLM", value=True)
        if not use_anonymized:
            st.warning("Modo menos seguro: o texto original sera enviado ao fornecedor LLM.")

    with text_col:
        st.session_state.source_text = st.text_area(
            "Texto base",
            value=st.session_state.source_text,
            height=260,
            placeholder="Escreve ou cola aqui o texto a analisar.",
        )
        render_text_selection_anonymization()

    actions_col, result_col = st.columns([0.9, 1.1], gap="large")

    with actions_col:
        if st.button("Anonimizar texto", type="primary", use_container_width=True):
            st.session_state.anonymizer.reset()
            anonymized, matches = st.session_state.anonymizer.anonymize(
                st.session_state.source_text,
                language=language,
            )
            st.session_state.anonymized_text = anonymized
            st.session_state.matches = matches
            st.session_state.llm_response = ""
            st.session_state.deanonymized_response = ""

        st.text_area("Texto anonimizado", value=st.session_state.anonymized_text, height=260)
        st.divider()
        render_manual_anonymization()
        st.divider()
        render_detection_report(show_debug=show_debug)

    with result_col:
        question = st.text_area(
            "Pergunta para a LLM",
            height=100,
            placeholder="Ex.: resume os factos relevantes, identifica riscos, prepara uma minuta...",
        )

        llm_text = st.session_state.anonymized_text if use_anonymized else st.session_state.source_text
        can_call_llm = bool(question.strip()) and bool(llm_text.strip())

        if st.button("Enviar para a LLM", disabled=not can_call_llm, use_container_width=True):
            try:
                prompt = build_prompt(question=question, text=llm_text, is_anonymized=use_anonymized)
                st.session_state.llm_response = call_llm(
                    provider=provider,
                    prompt=prompt,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                )
                st.session_state.deanonymized_response = ""
            except Exception as exc:
                st.error(str(exc))

        st.text_area("Resposta da LLM", height=220, key="llm_response")

        if st.button(
            "Desanonimizar resposta",
            disabled=not bool(st.session_state.llm_response.strip()),
            use_container_width=True,
        ):
            st.session_state.deanonymized_response = st.session_state.anonymizer.deanonymize(
                st.session_state.llm_response
            )
            unresolved_tokens = st.session_state.anonymizer.unresolved_tokens(st.session_state.llm_response)
            if unresolved_tokens:
                st.warning("Tokens sem correspondencia no vault: " + ", ".join(unresolved_tokens))

        st.text_area("Resposta desanonimizada", value=st.session_state.deanonymized_response, height=220)

    if show_vault:
        with st.expander("Vault da sessao", expanded=False):
            st.caption("Contem dados pessoais. Mantem fechado exceto para depuracao local.")
            st.json(st.session_state.anonymizer.vault)

    with st.expander("Verificacao rapida de tokens"):
        unknown_tokens = st.session_state.anonymizer.unresolved_tokens(st.session_state.llm_response)
        if unknown_tokens:
            st.warning("Tokens sem correspondencia no vault: " + ", ".join(unknown_tokens))
        else:
            st.write("Sem tokens desconhecidos na resposta atual.")


if __name__ == "__main__":
    main()
