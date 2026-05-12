# -*- coding: utf-8 -*-
import base64
import csv
import json
import math
import os
import re
import socket
import struct
import subprocess
import threading
import time
import tkinter as tk
import zipfile
from html import escape
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from urllib.request import urlopen

from EmailExtractor_OADV import (
    FIELDS,
    SOCIETY_FIELDS,
    build_search_url,
    build_societies_search_url,
    parse_result_blocks,
    parse_result_count,
    parse_society_result_blocks,
)


APP_FIELDS = FIELDS + ["zona_evento", "tipo_evento", "observacoes"]
SOCIETY_APP_FIELDS = SOCIETY_FIELDS + ["zona_evento", "tipo_evento", "observacoes"]
DEBUG_PORT = 9222
PROFILE_DIR = Path(".oa_browser_profile")


def find_browser():
    candidates = [
        os.environ.get("CHROME_PATH"),
        os.environ.get("EDGE_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def fetch_json(url, timeout=2):
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def browser_is_running():
    try:
        fetch_json(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
        return True
    except Exception:
        return False


def start_browser(url):
    if browser_is_running():
        open_url_in_debug_browser(url)
        return None

    browser = find_browser()
    if not browser:
        raise RuntimeError("Não encontrei Chrome ou Edge. Instale um deles ou defina CHROME_PATH/EDGE_PATH.")

    PROFILE_DIR.mkdir(exist_ok=True)
    args = [
        browser,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={PROFILE_DIR.resolve()}",
        "--new-window",
        url,
    ]
    return subprocess.Popen(args)


def open_url_in_debug_browser(url):
    targets = fetch_json(f"http://127.0.0.1:{DEBUG_PORT}/json/list")
    page = next((target for target in targets if target.get("type") == "page"), None)
    if not page:
        fetch_json(f"http://127.0.0.1:{DEBUG_PORT}/json/new?{quote(url, safe='')}")
        return

    client = ChromeDevToolsClient(page["webSocketDebuggerUrl"])
    try:
        client.call("Page.enable")
        client.call("Page.navigate", {"url": url})
    finally:
        client.close()


def get_portal_target():
    targets = fetch_json(f"http://127.0.0.1:{DEBUG_PORT}/json/list", timeout=5)
    for target in targets:
        if target.get("type") == "page" and "portal.oa.pt" in target.get("url", ""):
            return target
    return None


def websocket_key():
    return base64.b64encode(os.urandom(16)).decode("ascii")


class ChromeDevToolsClient:
    def __init__(self, websocket_url):
        parsed = urlparse(websocket_url)
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.path = parsed.path
        if parsed.query:
            self.path += "?" + parsed.query
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self._next_id = 1
        self._handshake()

    def _handshake(self):
        key = websocket_key()
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self.sock.recv(4096)
        if b" 101 " not in response:
            raise RuntimeError("O browser recusou a ligação de debug local.")

    def call(self, method, params=None):
        message_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"id": message_id, "method": method, "params": params or {}}).encode("utf-8")
        self._send_frame(payload)

        while True:
            data = self._recv_message()
            if not data:
                continue
            message = json.loads(data.decode("utf-8"))
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(message["error"].get("message", str(message["error"])))
                return message.get("result", {})

    def _send_frame(self, payload):
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + masked)

    def _recv_message(self):
        message = bytearray()
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == 8:
                return b""
            if opcode in {1, 0}:
                message.extend(payload)
            if fin:
                return bytes(message)

    def _recv_frame(self):
        first_two = self._recv_exact(2)
        if not first_two:
            return True, 8, b""
        fin = bool(first_two[0] & 0x80)
        opcode = first_two[0] & 0x0F
        length = first_two[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if first_two[1] & 0x80 else None
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return fin, opcode, payload

    def _recv_exact(self, size):
        chunks = []
        remaining = size
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                return b""
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def capture_current_page():
    target = get_portal_target()
    if not target:
        raise RuntimeError("Não encontrei uma aba aberta em portal.oa.pt.")

    client = ChromeDevToolsClient(target["webSocketDebuggerUrl"])
    try:
        result = client.call(
            "Runtime.evaluate",
            {
                "expression": "({url: location.href, html: document.documentElement.outerHTML})",
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
    finally:
        client.close()

    value = result.get("result", {}).get("value")
    if not value:
        raise RuntimeError("Não foi possível ler o HTML da página atual.")
    return value["html"], value["url"]


def navigate_portal_page(url):
    target = get_portal_target()
    if not target:
        raise RuntimeError("Não encontrei uma aba aberta em portal.oa.pt.")

    client = ChromeDevToolsClient(target["webSocketDebuggerUrl"])
    try:
        client.call("Page.enable")
        client.call("Page.navigate", {"url": url})
    finally:
        client.close()


def next_page_url(url):
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    current_page = int(params.get("page", "1") or "1")
    params["page"] = str(current_page + 1)
    return current_page + 1, urlunparse(parsed._replace(query=urlencode(params)))


def ensure_page_param(url):
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if not params.get("page"):
        params["page"] = "1"
    return urlunparse(parsed._replace(query=urlencode(params)))


def page_number_from_url(url):
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return int(params.get("page", "1") or "1")


def is_societies_url(url):
    return "pesquisa-de-sociedades-de-advogados" in urlparse(url).path


def is_lawyers_url(url):
    return "pesquisa-de-advogados" in urlparse(url).path and not is_societies_url(url)


def html_to_text(raw_html):
    text = re.sub(r"<script\b.*?</script>", " ", raw_html, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def read_existing_keys(path, key_fields):
    if not path.exists():
        return set()
    keys = set()
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            keys.add(tuple(row.get(field, "") for field in key_fields))
    return keys


def append_records(records, path, fieldnames=APP_FIELDS, key_fields=("cedula", "email")):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_existing_keys(path, key_fields)
    new_records = []
    for record in records:
        key = tuple(record.get(field, "") for field in key_fields)
        if key not in existing:
            existing.add(key)
            new_records.append(record)

    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(new_records)
    return len(new_records)


def export_xlsx_from_csv(csv_path):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return None

    xlsx_path = csv_path.with_suffix(".xlsx")
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{column_name(column_index)}{row_index}"
            safe_value = escape(value or "")
            cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{safe_value}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Advogados" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    with zipfile.ZipFile(xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    return xlsx_path


def column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OA - Recolha assistida de contactos")
        self.geometry("980x720")
        self.output_path = tk.StringVar(value=str(Path("contactos_oa_eventos.csv").resolve()))
        self.societies_output_path = tk.StringVar(value=str(Path("sociedades_oa_eventos.csv").resolve()))
        self.initial_url = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Pronto.")
        self.max_pages = tk.IntVar(value=1000)
        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        filters = ttk.LabelFrame(main, text="Pesquisa no portal")
        filters.pack(fill=tk.X)

        self._entry_var(filters, "Link inicial", 0, self.initial_url, "Opcional; se vazio começa na página 1 pelos filtros")
        self.conselho = self._entry(filters, "Conselho", 1, "L/P/C/E/F/M/A")
        self.nome = self._entry(filters, "Nome", 2, "")
        self.localidade = self._entry(filters, "Localidade", 3, "COIMBRA")
        self.codigo_postal = self._entry(filters, "Código postal", 4, "")
        self.apenas_ativos = tk.BooleanVar(value=True)
        ttk.Checkbutton(filters, text="Apenas ativos", variable=self.apenas_ativos).grid(row=5, column=1, sticky="w", pady=6)

        tags = ttk.LabelFrame(main, text="Segmentação para o evento")
        tags.pack(fill=tk.X, pady=(12, 0))
        self.zona_evento = self._entry(tags, "Zona", 0, "Coimbra")
        self.tipo_evento = self._entry(tags, "Tipo", 1, "Fiscal / Laboral / IA / Geral")
        self.observacoes = self._entry(tags, "Observações", 2, "")

        output = ttk.Frame(main)
        output.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(output, text="CSV advogados").pack(side=tk.LEFT)
        ttk.Entry(output, textvariable=self.output_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(output, text="Escolher", command=lambda: self.choose_output(self.output_path)).pack(side=tk.LEFT)

        societies_output = ttk.Frame(main)
        societies_output.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(societies_output, text="CSV sociedades").pack(side=tk.LEFT)
        ttk.Entry(societies_output, textvariable=self.societies_output_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(
            societies_output,
            text="Escolher",
            command=lambda: self.choose_output(self.societies_output_path),
        ).pack(side=tk.LEFT)

        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Abrir pesquisa no browser", command=self.open_browser).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Capturar página atual", command=self.capture_page).pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="Capturar até ao fim", command=self.capture_until_end).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Abrir Excel/CSV", command=self.open_output).pack(side=tk.LEFT)
        ttk.Label(buttons, text="Limite páginas").pack(side=tk.LEFT, padx=(14, 4))
        ttk.Spinbox(buttons, from_=1, to=5000, textvariable=self.max_pages, width=7).pack(side=tk.LEFT)

        society_buttons = ttk.Frame(main)
        society_buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(society_buttons, text="Abrir sociedades", command=self.open_societies_browser).pack(side=tk.LEFT)
        ttk.Button(
            society_buttons,
            text="Capturar sociedades página atual",
            command=self.capture_societies_page,
        ).pack(side=tk.LEFT, padx=8)
        ttk.Button(
            society_buttons,
            text="Capturar sociedades até ao fim",
            command=self.capture_societies_until_end,
        ).pack(side=tk.LEFT)
        ttk.Button(
            society_buttons,
            text="Abrir Excel sociedades",
            command=self.open_societies_output,
        ).pack(side=tk.LEFT, padx=8)

        notes = ttk.LabelFrame(main, text="Fluxo")
        notes.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        text = tk.Text(notes, wrap=tk.WORD, height=14)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(
            tk.END,
            "1. Cola um link inicial se quiseres começar numa pesquisa já filtrada; se ficar vazio, começa na página 1.\n"
            "2. Clica em 'Abrir pesquisa no browser' ou 'Abrir sociedades'.\n"
            "3. No browser, confirma o CAPTCHA se o portal pedir.\n"
            "4. Para recolher todas as páginas desde a página atual, clica em 'Capturar até ao fim'.\n"
            "5. Para sociedades, a app usa Registo + e-mail para evitar duplicados e gera XLSX próprio.\n\n"
            "Usa estes contactos só para convites proporcionais e relevantes, com identificação clara, fundamento legítimo, "
            "opção de oposição/remoção e sem envio massivo indiscriminado.",
        )
        text.configure(state=tk.DISABLED)

        ttk.Label(main, textvariable=self.status_text).pack(fill=tk.X, pady=(10, 0))

    def _entry(self, parent, label, row, placeholder):
        value = tk.StringVar(value="")
        self._entry_var(parent, label, row, value, placeholder)
        return value

    def _entry_var(self, parent, label, row, value, placeholder):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(8, 4), pady=4)
        entry = ttk.Entry(parent, textvariable=value)
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(parent, text=placeholder).grid(row=row, column=2, sticky="w", padx=4, pady=4)
        parent.columnconfigure(1, weight=1)

    def build_url(self):
        initial_url = self.initial_url.get().strip()
        if initial_url:
            if not is_lawyers_url(initial_url):
                raise RuntimeError("O link inicial não é da pesquisa de advogados. Usa 'Abrir sociedades' para links de sociedades.")
            return ensure_page_param(initial_url)

        return build_search_url(
            page=1,
            conselho_regional=self.conselho.get().strip(),
            nome=self.nome.get().strip(),
            localidade=self.localidade.get().strip(),
            codigo_postal=self.codigo_postal.get().strip(),
            apenas_ativos=self.apenas_ativos.get(),
        )

    def build_societies_url(self):
        initial_url = self.initial_url.get().strip()
        if initial_url:
            if not is_societies_url(initial_url):
                raise RuntimeError("O link inicial não é da pesquisa de sociedades. Usa 'Abrir pesquisa no browser' para advogados.")
            return ensure_page_param(initial_url)

        return build_societies_search_url(
            page=1,
            conselho_regional=self.conselho.get().strip(),
            nome=self.nome.get().strip(),
            localidade=self.localidade.get().strip(),
            codigo_postal=self.codigo_postal.get().strip(),
        )

    def choose_output(self, target_var):
        path = filedialog.asksaveasfilename(
            title="Guardar CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Todos os ficheiros", "*.*")],
        )
        if path:
            target_var.set(str(Path(path).with_suffix(".csv")))

    def open_browser(self):
        self.run_background(lambda: start_browser(self.build_url()), "Browser aberto. Resolve o CAPTCHA no browser, se aparecer.")

    def open_societies_browser(self):
        self.run_background(
            lambda: start_browser(self.build_societies_url()),
            "Pesquisa de sociedades aberta. Resolve o CAPTCHA no browser, se aparecer.",
        )

    def capture_page(self):
        zona_evento = self.zona_evento.get().strip()
        tipo_evento = self.tipo_evento.get().strip()
        observacoes = self.observacoes.get().strip()
        output = Path(self.output_path.get()).with_suffix(".csv")

        def work():
            html, url = capture_current_page()
            records = parse_result_blocks(html, url)
            for record in records:
                record["zona_evento"] = zona_evento
                record["tipo_evento"] = tipo_evento
                record["observacoes"] = observacoes
            saved = append_records(records, output)
            xlsx_path = export_xlsx_from_csv(output)
            emails = sum(1 for record in records if record.get("email"))
            return f"Capturados {len(records)} registos; {emails} com e-mail; {saved} novos gravados. Excel: {xlsx_path.name}"

        self.run_background(work)

    def capture_until_end(self):
        zona_evento = self.zona_evento.get().strip()
        tipo_evento = self.tipo_evento.get().strip()
        observacoes = self.observacoes.get().strip()
        output = Path(self.output_path.get()).with_suffix(".csv")
        max_pages = int(self.max_pages.get())

        def work():
            total_seen = 0
            total_saved = 0
            total_emails = 0
            empty_pages = 0
            first_total = None
            total_pages = None

            for page_index in range(max_pages):
                html, url = capture_current_page()
                records = parse_result_blocks(html, url)
                page_text = html_to_text(html)
                shown, total = parse_result_count(page_text)

                if first_total is None and total:
                    first_total = total
                    page_size = len(records) or 10
                    total_pages = max(1, math.ceil(total / page_size))

                if not records:
                    empty_pages += 1
                    if empty_pages >= 2:
                        break
                else:
                    empty_pages = 0

                for record in records:
                    record["zona_evento"] = zona_evento
                    record["tipo_evento"] = tipo_evento
                    record["observacoes"] = observacoes

                saved = append_records(records, output)
                total_seen += len(records)
                total_saved += saved
                total_emails += sum(1 for record in records if record.get("email"))

                current_page = page_number_from_url(url)
                self.after(
                    0,
                    lambda p=current_page, r=len(records), s=total_saved: self.status_text.set(
                        f"Página {p}: {r} registos. Novos gravados até agora: {s}."
                    ),
                )

                if total_pages and current_page >= total_pages:
                    break

                _, next_url = next_page_url(url)
                navigate_portal_page(next_url)
                time.sleep(2.5)

            xlsx_path = export_xlsx_from_csv(output)
            return (
                f"Terminado. Lidos {total_seen} registos; {total_emails} com e-mail; "
                f"{total_saved} novos gravados. Excel: {xlsx_path.name if xlsx_path else 'não gerado'}."
            )

        self.run_background(work)

    def capture_societies_page(self):
        zona_evento = self.zona_evento.get().strip()
        tipo_evento = self.tipo_evento.get().strip()
        observacoes = self.observacoes.get().strip()
        output = Path(self.societies_output_path.get()).with_suffix(".csv")

        def work():
            html, url = capture_current_page()
            records = parse_society_result_blocks(html, url)
            for record in records:
                record["zona_evento"] = zona_evento
                record["tipo_evento"] = tipo_evento
                record["observacoes"] = observacoes
            saved = append_records(
                records,
                output,
                fieldnames=SOCIETY_APP_FIELDS,
                key_fields=("conselho_regional", "registo", "email", "nome"),
            )
            xlsx_path = export_xlsx_from_csv(output)
            emails = sum(1 for record in records if record.get("email"))
            return f"Sociedades: {len(records)} registos; {emails} com e-mail; {saved} novos. Excel: {xlsx_path.name}"

        self.run_background(work)

    def capture_societies_until_end(self):
        zona_evento = self.zona_evento.get().strip()
        tipo_evento = self.tipo_evento.get().strip()
        observacoes = self.observacoes.get().strip()
        output = Path(self.societies_output_path.get()).with_suffix(".csv")
        max_pages = int(self.max_pages.get())

        def work():
            total_seen = 0
            total_saved = 0
            total_emails = 0
            empty_pages = 0
            first_total = None
            total_pages = None

            for page_index in range(max_pages):
                html, url = capture_current_page()
                records = parse_society_result_blocks(html, url)
                page_text = html_to_text(html)
                shown, total = parse_result_count(page_text)

                if first_total is None and total:
                    first_total = total
                    page_size = len(records) or 10
                    total_pages = max(1, math.ceil(total / page_size))

                if not records:
                    empty_pages += 1
                    if empty_pages >= 2:
                        break
                else:
                    empty_pages = 0

                for record in records:
                    record["zona_evento"] = zona_evento
                    record["tipo_evento"] = tipo_evento
                    record["observacoes"] = observacoes

                saved = append_records(
                    records,
                    output,
                    fieldnames=SOCIETY_APP_FIELDS,
                    key_fields=("conselho_regional", "registo", "email", "nome"),
                )
                total_seen += len(records)
                total_saved += saved
                total_emails += sum(1 for record in records if record.get("email"))

                current_page = page_number_from_url(url)
                self.after(
                    0,
                    lambda p=current_page, r=len(records), s=total_saved: self.status_text.set(
                        f"Sociedades página {p}: {r} registos. Novos gravados até agora: {s}."
                    ),
                )

                if total_pages and current_page >= total_pages:
                    break

                _, next_url = next_page_url(url)
                navigate_portal_page(next_url)
                time.sleep(2.5)

            xlsx_path = export_xlsx_from_csv(output)
            return (
                f"Sociedades terminado. Lidos {total_seen} registos; {total_emails} com e-mail; "
                f"{total_saved} novos gravados. Excel: {xlsx_path.name if xlsx_path else 'não gerado'}."
            )

        self.run_background(work)

    def open_output(self):
        csv_path = Path(self.output_path.get()).with_suffix(".csv")
        xlsx_path = csv_path.with_suffix(".xlsx")
        path = xlsx_path if xlsx_path.exists() else csv_path
        if not path.exists():
            messagebox.showinfo("Ficheiro", "O ficheiro ainda não existe.")
            return
        os.startfile(path)

    def open_societies_output(self):
        csv_path = Path(self.societies_output_path.get()).with_suffix(".csv")
        xlsx_path = csv_path.with_suffix(".xlsx")
        path = xlsx_path if xlsx_path.exists() else csv_path
        if not path.exists():
            messagebox.showinfo("Ficheiro", "O ficheiro de sociedades ainda não existe.")
            return
        os.startfile(path)

    def run_background(self, func, success_message=None):
        self.status_text.set("A trabalhar...")

        def runner():
            try:
                result = func()
                message = success_message or str(result)
                self.after(0, lambda: self.status_text.set(message))
            except Exception as exc:
                self.after(0, lambda: self.show_error(exc))

        threading.Thread(target=runner, daemon=True).start()

    def show_error(self, exc):
        self.status_text.set("Erro.")
        messagebox.showerror("Erro", str(exc))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
