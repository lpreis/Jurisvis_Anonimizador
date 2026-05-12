import argparse
import csv
import html
from html.parser import HTMLParser
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SEARCH_URL = "https://portal.oa.pt/advogados/pesquisa-de-advogados/"
SOCIETIES_SEARCH_URL = "https://portal.oa.pt/advogados/pesquisa-de-sociedades-de-advogados/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; jurisvis-oa-public-directory/1.0; "
        "+uso-legitimo-dados-publicos)"
    )
}

FIELDS = [
    "nome",
    "estado",
    "conselho_regional",
    "cedula",
    "localidade",
    "data_inscricao",
    "email",
    "morada",
    "codigo_postal",
    "telefone",
    "telemovel",
    "fax",
    "fax_registado",
    "url_fonte",
]

LABEL_TO_FIELD = {
    "Conselho Regional": "conselho_regional",
    "Cédula": "cedula",
    "Localidade": "localidade",
    "Data de Inscrição": "data_inscricao",
    "Email": "email",
    "Morada": "morada",
    "Código Postal": "codigo_postal",
    "Telefone": "telefone",
    "Telemóvel": "telemovel",
    "Fax": "fax",
    "Fax registado": "fax_registado",
}

SOCIETY_FIELDS = [
    "nome",
    "conselho_regional",
    "registo",
    "localidade",
    "data_constituicao",
    "email",
    "morada",
    "codigo_postal",
    "telefone",
    "telemovel",
    "fax",
    "url_fonte",
]

SOCIETY_LABEL_TO_FIELD = {
    "Conselho Regional": "conselho_regional",
    "Registo": "registo",
    "Localidade": "localidade",
    "Data de Constituição": "data_constituicao",
    "Email": "email",
    "Morada": "morada",
    "Código Postal": "codigo_postal",
    "Telefone": "telefone",
    "Telemóvel": "telemovel",
    "Fax": "fax",
}


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def build_search_url(
    *,
    page,
    conselho_regional="",
    cedula="",
    nome="",
    localidade="",
    morada="",
    codigo_postal="",
    apenas_ativos=True,
    ordenar_por="Nome",
    ordenacao="Ascendente",
):
    params = {
        "ce": cedula,
        "cg": conselho_regional,
        "cp": codigo_postal,
        "l": "",
        "lo": localidade,
        "m": morada,
        "n": nome,
        "o": "0" if ordenacao.lower().startswith("asc") else "1",
        "op": ordenar_por,
        "page": str(page),
    }

    if apenas_ativos:
        params = {"a": "on", **params}

    return f"{SEARCH_URL}?{urlencode(params)}"


def build_societies_search_url(
    *,
    page,
    conselho_regional="",
    registo="",
    nome="",
    localidade="",
    morada="",
    codigo_postal="",
    ordenar_por="",
    ordenacao="Ascendente",
):
    params = {
        "cg": conselho_regional,
        "r": registo,
        "n": nome,
        "lo": localidade,
        "m": morada,
        "cp": codigo_postal,
        "op": ordenar_por,
        "o": "0" if ordenacao.lower().startswith("asc") else "1",
        "page": str(page),
    }
    return f"{SOCIETIES_SEARCH_URL}?{urlencode(params)}"


def fetch_page(url):
    request = Request(url, headers=HEADERS)
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        status = getattr(exc, "code", None)
        if status != 403:
            raise
        raise RuntimeError(
            "Acesso bloqueado pelo servidor. Reduza o volume de pedidos e nao tente contornar protecoes tecnicas."
        ) from exc


class SearchResultsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self._capture = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        if tag in {"h3", "h4", "li"}:
            self._flush_buffer()
            self._capture = "heading" if tag in {"h3", "h4"} else "li"
            self._buffer = []

    def handle_endtag(self, tag):
        if self._capture == "heading" and tag in {"h3", "h4"}:
            self._flush_buffer()
        elif self._capture == "li" and tag == "li":
            self._flush_buffer()

    def handle_data(self, data):
        text = clean_text(html.unescape(data))
        if not text:
            return

        if self._capture:
            self._buffer.append(text)
        else:
            self.tokens.append(("text", text))

    def _flush_buffer(self):
        if not self._capture:
            return

        text = clean_text(" ".join(self._buffer))
        if text:
            self.tokens.append((self._capture, text))

        self._capture = None
        self._buffer = []


def parse_result_count(text):
    match = re.search(r"Foram encontrados\s+(\d+)(?:\s+de\s+(\d+))?\s+resultados", text, re.I)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2) or match.group(1))


def field_from_items(items, label):
    field = LABEL_TO_FIELD[label]
    for item in items:
        text = clean_text(item)
        if text.lower().startswith(label.lower()):
            return clean_text(text[len(label) :])
    return ""


def field_from_items_map(items, label, label_to_field):
    for item in items:
        text = clean_text(item)
        if text.lower().startswith(label.lower()):
            return clean_text(text[len(label) :])
    return ""


def parse_result_blocks(html, source_url):
    parser = SearchResultsParser()
    parser.feed(html)
    parser.close()

    records = []
    tokens = parser.tokens

    for index, (token_type, name) in enumerate(tokens):
        if token_type != "heading":
            continue

        if not name or name.lower() in {"pesquisa de advogados", "0 resultados"}:
            continue

        block_items = []
        block_texts = []
        for next_type, next_text in tokens[index + 1 :]:
            if next_type == "heading":
                break
            block_texts.append(next_text)
            if next_type == "li":
                block_items.append(next_text)

        joined_block = " ".join(block_texts)
        status = ""
        for candidate in ("Activo", "Inativo", "Suspenso"):
            if re.search(rf"\b{candidate}\b", joined_block, re.I):
                status = candidate
                break

        if not status or not any(item.startswith("Cédula") for item in block_items):
            continue

        record = {field: "" for field in FIELDS}
        record["nome"] = name
        record["estado"] = status
        record["url_fonte"] = source_url

        for label, field in LABEL_TO_FIELD.items():
            record[field] = field_from_items(block_items, label)

        # O portal protege os e-mails dos advogados com confirmacao anti-robot.
        # Este script so grava o e-mail quando ele estiver visivel no HTML recebido.
        records.append(record)

    return records


def parse_society_result_blocks(html, source_url):
    parser = SearchResultsParser()
    parser.feed(html)
    parser.close()

    records = []
    tokens = parser.tokens

    for index, (token_type, name) in enumerate(tokens):
        if token_type != "heading":
            continue

        lowered_name = name.lower()
        if not name or lowered_name in {"pesquisa de sociedades", "0 resultados"}:
            continue

        block_items = []
        for next_type, next_text in tokens[index + 1 :]:
            if next_type == "heading":
                break
            if next_type == "li":
                block_items.append(next_text)

        if not any(item.startswith("Registo") for item in block_items):
            continue

        record = {field: "" for field in SOCIETY_FIELDS}
        record["nome"] = name
        record["url_fonte"] = source_url

        for label, field in SOCIETY_LABEL_TO_FIELD.items():
            record[field] = field_from_items_map(block_items, label, SOCIETY_LABEL_TO_FIELD)

        records.append(record)

    return records


def scrape_oa_search_pages(
    *,
    start_page=1,
    end_page=1,
    delay_seconds=3,
    conselho_regional="",
    cedula="",
    nome="",
    localidade="",
    morada="",
    codigo_postal="",
    apenas_ativos=True,
    ordenar_por="Nome",
    ordenacao="Ascendente",
):
    all_records = []

    for page in range(start_page, end_page + 1):
        url = build_search_url(
            page=page,
            conselho_regional=conselho_regional,
            cedula=cedula,
            nome=nome,
            localidade=localidade,
            morada=morada,
            codigo_postal=codigo_postal,
            apenas_ativos=apenas_ativos,
            ordenar_por=ordenar_por,
            ordenacao=ordenacao,
        )
        print(f"A processar pagina {page}: {url}")

        html = fetch_page(url)
        records = parse_result_blocks(html, url)
        print(f"  {len(records)} registos extraidos.")

        all_records.extend(records)

        if page < end_page:
            time.sleep(delay_seconds)

    seen = set()
    unique_records = []
    for record in all_records:
        key = (record.get("cedula"), record.get("nome"), record.get("url_fonte"))
        if key in seen:
            continue
        seen.add(key)
        unique_records.append(record)

    return unique_records


def save_outputs(records, output_path):
    output_path = Path(output_path)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    excel_path = output_path.with_suffix(".xlsx")
    try:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Advogados"
        sheet.append(FIELDS)
        for record in records:
            sheet.append([record.get(field, "") for field in FIELDS])
        workbook.save(excel_path)
        print(f"Ficheiros gravados: {output_path} e {excel_path}")
    except ImportError:
        print(f"Ficheiro gravado: {output_path}")
        print("Para gravar Excel, instale openpyxl: py -m pip install openpyxl")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extrai dados publicamente visiveis da pesquisa de advogados da Ordem dos Advogados."
    )
    parser.add_argument("--conselho", default="", help="Codigo do Conselho Regional, por exemplo L, P, C, E, F, M ou A.")
    parser.add_argument("--cedula", default="", help="Numero/codigo da cedula.")
    parser.add_argument("--nome", default="", help="Nome a pesquisar.")
    parser.add_argument("--localidade", default="", help="Localidade a pesquisar.")
    parser.add_argument("--morada", default="", help="Morada a pesquisar.")
    parser.add_argument("--codigo-postal", default="", help="Codigo postal a pesquisar.")
    parser.add_argument("--pagina-inicial", type=int, default=1)
    parser.add_argument("--pagina-final", type=int, default=1)
    parser.add_argument("--espera", type=float, default=3, help="Segundos de espera entre paginas.")
    parser.add_argument("--incluir-inativos", action="store_true", help="Nao limita a pesquisa a advogados ativos.")
    parser.add_argument("--saida", default="contactos_oa_pesquisa_filtrada.csv")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.pagina_final < args.pagina_inicial:
        raise SystemExit("--pagina-final tem de ser maior ou igual a --pagina-inicial.")

    records = scrape_oa_search_pages(
        start_page=args.pagina_inicial,
        end_page=args.pagina_final,
        delay_seconds=args.espera,
        conselho_regional=args.conselho,
        cedula=args.cedula,
        nome=args.nome,
        localidade=args.localidade,
        morada=args.morada,
        codigo_postal=args.codigo_postal,
        apenas_ativos=not args.incluir_inativos,
    )

    save_outputs(records, args.saida)
    print(f"Total de registos: {len(records)}")
    for record in records[:10]:
        print(f"- {record['nome']} | {record['cedula']} | {record['localidade']} | {record['telefone']}")


if __name__ == "__main__":
    main()
