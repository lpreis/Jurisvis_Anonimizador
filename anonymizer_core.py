from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable


TOKEN_RE = re.compile(r"\[[^\[\]]+\]")
TOKEN_PARTS_RE = re.compile(r"^\[?([^\[\]\d]+?)[_\s-]*(\d+)\]?$")

ENTITY_TYPES = [
    "PESSOA",
    "ORGANIZACAO",
    "LOCALIZACAO",
    "EMAIL",
    "TELEFONE",
    "NIF",
    "NIPC",
    "IBAN",
    "FATURA",
    "PROCESSO",
    "CONTRATO",
    "CARTAO_CIDADAO",
    "CEDULA_PROFISSIONAL",
    "CODIGO_POSTAL",
    "CARTAO_CREDITO",
    "DATA",
]

TOKEN_TYPE_ALIASES = {
    "PERSON": "PESSOA",
    "PESSOA": "PESSOA",
    "ORGANIZATION": "ORGANIZACAO",
    "ORGANISATION": "ORGANIZACAO",
    "ORGANIZACAO": "ORGANIZACAO",
    "ORG": "ORGANIZACAO",
    "LOCATION": "LOCALIZACAO",
    "LOCALIZACAO": "LOCALIZACAO",
    "ADDRESS": "LOCALIZACAO",
    "MORADA": "LOCALIZACAO",
    "PHONE": "TELEFONE",
    "PHONE_NUMBER": "TELEFONE",
    "TELEFONE": "TELEFONE",
    "EMAIL": "EMAIL",
    "EMAIL_ADDRESS": "EMAIL",
    "NIF": "NIF",
    "NIPC": "NIPC",
    "IBAN": "IBAN",
    "IBAN_CODE": "IBAN",
    "PROCESSO": "PROCESSO",
    "PROCESS": "PROCESSO",
    "CEDULA": "CEDULA_PROFISSIONAL",
    "CEDULA_PROFISSIONAL": "CEDULA_PROFISSIONAL",
    "FATURA": "FATURA",
    "FACTURA": "FATURA",
    "CONTRATO": "CONTRATO",
    "CARTAO_CIDADAO": "CARTAO_CIDADAO",
    "CC": "CARTAO_CIDADAO",
    "CODIGO_POSTAL": "CODIGO_POSTAL",
    "POSTAL_CODE": "CODIGO_POSTAL",
    "CARTAO_CREDITO": "CARTAO_CREDITO",
    "CREDIT_CARD": "CARTAO_CREDITO",
    "DATA": "DATA",
    "DATE": "DATA",
    "DATE_TIME": "DATA",
}

UPPER_PT = r"A-ZÀ-ÖØ-Þ"
LOWER_PT = r"a-zà-öø-ÿ"
WORD_PT = r"A-Za-zÀ-ÖØ-öø-ÿ"

COMPANY_SUFFIX_RE = re.compile(
    rf"\b[{UPPER_PT}][{WORD_PT}0-9&.'-]*"
    rf"(?:\s+(?:de|da|do|das|dos|e|&|[{UPPER_PT}][{WORD_PT}0-9&.'-]*)){{0,6}}"
    r",?\s+(?:Lda\.?|LDA\.?|Limitada|S\.?\s*A\.?|SA|Unipessoal\s+Lda\.?)\b\.?",
)

ADDRESS_RE = re.compile(
    r"\b(?:Rua|R\.|Avenida|Av\.|Travessa|Tv\.|Praca|Praça|Praceta|Largo|Estrada|Alameda|Beco|"
    r"Calcada|Calçada|Rotunda|Urbanizacao|Urbanização|Quinta|Lugar|Caminho)\s+"
    rf"[{UPPER_PT}0-9][^,\n]*?,?\s+"
    r"(?:n\.?\s*(?:o|º)\s*)?\d+[A-Za-z]?"
    r"(?:\s*[-/]\s*\d+[A-Za-z]?)?"
    r"(?:\s*,?\s*(?:(?:\d{1,2}\s*\.?\s*(?:º|o|andar))|(?:esq\.?|dto\.?|frente|tras|trás)|"
    r"(?:[A-Z]?\d{1,2}[A-Z])|(?:ap\.?|apt\.?|apartamento|fracao|fração)\s*[A-Z0-9-]+)){0,3}"
    rf"(?:\s*,?\s*\d{{4}}-\d{{3}}\s+[{UPPER_PT}][{WORD_PT}.''-]+(?:\s+[{UPPER_PT}][{WORD_PT}.''-]+){{0,3}})?"
    rf"(?:\s*,?\s+[{UPPER_PT}][{WORD_PT}.''-]+(?:\s+[{UPPER_PT}][{WORD_PT}.''-]+){{0,2}})?",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class EntityMatch:
    start: int
    end: int
    entity_type: str
    text: str
    score: float
    source: str


@dataclass(frozen=True)
class DetectionReport:
    matches: list[EntityMatch]
    rejected: list[EntityMatch]

    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for match in self.matches:
            counts[match.entity_type] = counts.get(match.entity_type, 0) + 1
        return counts


class ReversibleAnonymizer:
    def __init__(self, warning_callback: Callable[[str], None] | None = None) -> None:
        self.vault: dict[str, str] = {}
        self.reverse_vault: dict[str, str] = {}
        self.canonical_vault: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.last_report = DetectionReport(matches=[], rejected=[])
        self.warning_callback = warning_callback
        self.presidio_analyzer = self._build_presidio_analyzer()

    def anonymize(self, text: str, language: str = "pt") -> tuple[str, list[EntityMatch]]:
        report = self.detect_with_report(text, language=language)
        anonymized = text
        tokens_by_span: dict[tuple[int, int], str] = {}

        for match in sorted(report.matches, key=lambda item: item.start):
            tokens_by_span[(match.start, match.end)] = self._token_for(match.entity_type, match.text)

        for match in sorted(report.matches, key=lambda item: item.start, reverse=True):
            token = tokens_by_span[(match.start, match.end)]
            anonymized = anonymized[: match.start] + token + anonymized[match.end :]

        return anonymized, report.matches

    def deanonymize(self, text: str) -> str:
        token_aliases = self._token_aliases()

        def replace_token(match: re.Match[str]) -> str:
            token = match.group(0)
            return token_aliases.get(self._normalize_token(token), token)

        return TOKEN_RE.sub(replace_token, text)

    def unresolved_tokens(self, text: str) -> list[str]:
        token_aliases = self._token_aliases()
        return [
            token
            for token in sorted(set(TOKEN_RE.findall(text)))
            if self._normalize_token(token) not in token_aliases
        ]

    def detect(self, text: str, language: str = "pt") -> list[EntityMatch]:
        return self.detect_with_report(text, language=language).matches

    def detect_with_report(self, text: str, language: str = "pt") -> DetectionReport:
        matches = self._regex_matches(text)

        if self.presidio_analyzer is not None:
            try:
                presidio_results = self.presidio_analyzer.analyze(
                    text=text,
                    language=language,
                    score_threshold=0.35,
                )
                for result in presidio_results:
                    value = text[result.start : result.end]
                    matches.append(
                        EntityMatch(
                            start=result.start,
                            end=result.end,
                            entity_type=self._normalize_type(result.entity_type),
                            text=value,
                            score=float(result.score),
                            source="presidio",
                        )
                    )
            except Exception as exc:
                if self.warning_callback is not None:
                    self.warning_callback(f"Presidio falhou; foi usado o fallback regex. Detalhe: {exc}")

        selected, rejected = self._remove_overlaps(self._refine_matches(matches))
        self.last_report = DetectionReport(matches=selected, rejected=rejected)
        return self.last_report

    def reset(self) -> None:
        self.vault.clear()
        self.reverse_vault.clear()
        self.canonical_vault.clear()
        self.counters.clear()
        self.last_report = DetectionReport(matches=[], rejected=[])

    def add_manual_entity(self, text: str, entity_type: str) -> str:
        return self._token_for(self._normalize_type(entity_type), text)

    def replace_manual_entity(self, text: str, value: str, entity_type: str) -> tuple[str, str]:
        token = self.add_manual_entity(value, entity_type)
        return replace_literal(text, value, token), token

    def get_entity_suggestions(self, text: str) -> list[tuple[str, float]]:
        if not text.strip():
            return []
        suggestions: dict[str, float] = {}
        for entity_type, pattern, score, validator in REGEX_PATTERNS:
            flags = 0 if entity_type in {"ORGANIZACAO", "PESSOA"} else re.IGNORECASE
            if re.search(pattern, text, flags=flags):
                if validator is None or validator(text):
                    suggestions[entity_type] = score
        return sorted(suggestions.items(), key=lambda item: item[1], reverse=True)

    def find_similar_in_vault(self, text: str, entity_type: str | None = None) -> list[tuple[str, str, float]]:
        if not text.strip():
            return []

        similar: list[tuple[str, str, float]] = []
        text_key = canonical_text(text)
        for token, value in self.vault.items():
            token_match = TOKEN_PARTS_RE.match(token)
            token_type = self._normalize_token_type(token_match.group(1)) if token_match else ""
            if entity_type and token_type != self._normalize_type(entity_type):
                continue
            similarity = SequenceMatcher(None, text_key, canonical_text(value)).ratio()
            if similarity > 0.6:
                similar.append((token, value, similarity))
        return sorted(similar, key=lambda item: item[2], reverse=True)

    def _token_for(self, entity_type: str, value: str) -> str:
        existing = self.reverse_vault.get(value)
        if existing:
            return existing

        canonical_key = self._canonical_key(entity_type, value)
        existing = self.canonical_vault.get(canonical_key)
        if existing:
            self.reverse_vault[value] = existing
            return existing

        self.counters[entity_type] = self.counters.get(entity_type, 0) + 1
        token = f"[{entity_type}_{self.counters[entity_type]}]"
        self.vault[token] = value
        self.reverse_vault[value] = token
        self.canonical_vault[canonical_key] = token
        return token

    def _token_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for token, value in self.vault.items():
            normalized = self._normalize_token(token)
            aliases[normalized] = value

            parts = TOKEN_PARTS_RE.match(token)
            if not parts:
                continue

            token_type, token_number = parts.groups()
            normalized_type = self._normalize_token_type(token_type)
            aliases[f"{normalized_type}_{token_number}"] = value
            aliases[f"{normalized_type}{token_number}"] = value
        return aliases

    @classmethod
    def _normalize_token(cls, token: str) -> str:
        parts = TOKEN_PARTS_RE.match(token.strip())
        if not parts:
            return cls._ascii_upper(token.strip("[]"))
        token_type, token_number = parts.groups()
        return f"{cls._normalize_token_type(token_type)}_{token_number}"

    @classmethod
    def _normalize_token_type(cls, token_type: str) -> str:
        normalized = cls._ascii_upper(token_type)
        normalized = re.sub(r"[^A-Z0-9]+", "_", normalized).strip("_")
        return TOKEN_TYPE_ALIASES.get(normalized, normalized)

    @classmethod
    def _normalize_type(cls, entity_type: str) -> str:
        return cls._normalize_token_type(entity_type)

    @staticmethod
    def _ascii_upper(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return normalized.upper()

    def _canonical_key(self, entity_type: str, value: str) -> str:
        normalized = canonical_text(value)

        if entity_type in {"NIF", "NIPC", "TELEFONE", "CARTAO_CREDITO", "CARTAO_CIDADAO"}:
            return f"{entity_type}:{digits_only(normalized)}"
        if entity_type in {"PROCESSO", "FATURA", "CONTRATO"}:
            return f"{entity_type}:{re.sub(r'[^a-z0-9]', '', normalized)}"
        if entity_type == "ORGANIZACAO":
            normalized = re.sub(r"^(?:o|a|os|as)\s+", "", normalized)
            normalized = normalized.replace("&", " e ")
            normalized = re.sub(r"\bs\.?\s*a\.?\b", "sa", normalized)
            normalized = re.sub(r"\bl\.?\s*d\.?\s*a\.?\b", "lda", normalized)
            normalized = re.sub(r"\blimitada\b", "lda", normalized)
            normalized = re.sub(r"[,.;:()\"']", " ", normalized)
            normalized = re.sub(r"\s+", " ", normalized).strip()
        if entity_type in {"EMAIL", "IBAN"}:
            return f"{entity_type}:{re.sub(r'\s+', '', normalized)}"
        return f"{entity_type}:{normalized}"

    def _build_presidio_analyzer(self):
        try:
            from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            import spacy

            if not spacy.util.is_package("pt_core_news_lg"):
                return None

            provider = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "pt", "model_name": "pt_core_news_lg"}],
                }
            )
            analyzer = AnalyzerEngine(
                nlp_engine=provider.create_engine(),
                supported_languages=["pt"],
            )
            for entity, pattern, score, _validator in REGEX_PATTERNS:
                analyzer.registry.add_recognizer(
                    PatternRecognizer(
                        supported_entity=entity,
                        patterns=[Pattern(name=f"{entity.lower()}_pattern", regex=pattern, score=score)],
                        supported_language="pt",
                    )
                )
            return analyzer
        except Exception:
            return None

    def _regex_matches(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        for entity_type, pattern, score, validator in REGEX_PATTERNS:
            flags = 0 if entity_type in {"ORGANIZACAO", "PESSOA"} else re.IGNORECASE
            for result in re.finditer(pattern, text, flags=flags):
                value = result.group(0)
                if validator is not None and not validator(value):
                    continue
                if entity_type == "PESSOA" and looks_like_non_person(value):
                    continue
                matches.append(
                    EntityMatch(
                        start=result.start(),
                        end=result.end(),
                        entity_type=entity_type,
                        text=value,
                        score=score,
                        source="regex",
                    )
                )
        return matches

    @staticmethod
    def _refine_matches(matches: list[EntityMatch]) -> list[EntityMatch]:
        refined: list[EntityMatch] = []
        for match in matches:
            if match.entity_type == "LOCALIZACAO":
                trimmed = trim_address(match.text)
                if trimmed != match.text:
                    refined.append(
                        EntityMatch(
                            start=match.start,
                            end=match.start + len(trimmed),
                            entity_type=match.entity_type,
                            text=trimmed,
                            score=match.score,
                            source=match.source,
                        )
                    )
                    continue

            if match.entity_type == "ORGANIZACAO":
                company_matches = list(COMPANY_SUFFIX_RE.finditer(match.text))
                if company_matches:
                    company = company_matches[-1]
                    company_text = company.group(0)
                    article_match = re.match(r"^(?:O|A|Os|As)\s+", company_text)
                    article_offset = article_match.end() if article_match else 0
                    refined.append(
                        EntityMatch(
                            start=match.start + company.start() + article_offset,
                            end=match.start + company.end(),
                            entity_type=match.entity_type,
                            text=company_text[article_offset:],
                            score=max(match.score, 0.98),
                            source=match.source,
                        )
                    )
                    continue
            refined.append(match)
        return refined

    @staticmethod
    def _remove_overlaps(matches: list[EntityMatch]) -> tuple[list[EntityMatch], list[EntityMatch]]:
        ordered = sorted(matches, key=lambda item: (-item.score, -(item.end - item.start), item.start))
        selected: list[EntityMatch] = []
        rejected: list[EntityMatch] = []

        for match in ordered:
            has_overlap = any(not (match.end <= saved.start or match.start >= saved.end) for saved in selected)
            if has_overlap:
                rejected.append(match)
            else:
                selected.append(match)

        return sorted(selected, key=lambda item: item.start), sorted(rejected, key=lambda item: item.start)


def replace_literal(text: str, value: str, token: str) -> str:
    if not value:
        return text
    return text.replace(value, token)


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.casefold().strip()
    normalized = re.sub(r"[,.;:()\"']", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def is_valid_pt_tax_id(value: str) -> bool:
    digits = digits_only(value)
    if len(digits) != 9 or digits[0] not in "1235689":
        return False
    total = sum(int(digit) * weight for digit, weight in zip(digits[:8], range(9, 1, -1)))
    check = 11 - (total % 11)
    if check >= 10:
        check = 0
    return check == int(digits[-1])


def is_valid_iban(value: str) -> bool:
    iban = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"PT50\d{21}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(char, 36)) for char in rearranged)
    return int(numeric) % 97 == 1


def is_valid_luhn(value: str) -> bool:
    digits = digits_only(value)
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        number = int(char)
        if index % 2 == parity:
            number *= 2
            if number > 9:
                number -= 9
        checksum += number
    return checksum % 10 == 0


def looks_like_non_person(value: str) -> bool:
    blacklist = {
        "juizo",
        "central",
        "civel",
        "tribunal",
        "camara",
        "corte",
        "judicial",
        "avenida",
        "rua",
        "travessa",
        "praca",
        "ministerio",
        "autoridade",
        "instituto",
        "servicos",
        "solucoes",
        "empresa",
        "industria",
        "banco",
        "seguros",
        "advocacia",
    }
    normalized = canonical_text(value)
    return any(word in normalized for word in blacklist)


def trim_address(value: str) -> str:
    cut_markers = [
        ", intentou ",
        ", apresentou ",
        ", requereu ",
        ", declarou ",
        ", celebrou ",
        ", contra ",
        ", nos autos ",
    ]
    lower = value.casefold()
    cut_at = len(value)
    for marker in cut_markers:
        index = lower.find(marker)
        if index != -1:
            cut_at = min(cut_at, index)
    return value[:cut_at].rstrip(" ,.;")


REGEX_PATTERNS: list[tuple[str, str, float, Callable[[str], bool] | None]] = [
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", 0.95, None),
    ("CONTRATO", r"\b(?:Contrato\s+)?[A-Z0-9]{2,}(?:-[A-Z0-9]{2,})+-\d{4}/\d{1,10}\b", 0.93, None),
    ("CARTAO_CIDADAO", r"\b(?:Cart[aã]o\s+de\s+Cidad[aã]o|CC)\s+n\.?\s*(?:o|º)\s*\d{8}\s*\d\s*[A-Z0-9]{3}\b", 0.96, None),
    ("FATURA", r"\b(?:FT|FS|FR|FTR|FAC|NC|ND)\s*\d{4}/\d{1,10}\b", 0.94, None),
    ("LOCALIZACAO", ADDRESS_RE.pattern, 0.99, None),
    ("NIPC", r"\b(?:N\.?\s*I\.?\s*P\.?\s*C\.?|pessoa\s+coletiva|pessoa\s+colectiva)\s*(?:n\.?\s*(?:o|º)\s*)?[569]\d{2}\s?\d{3}\s?\d{3}\b", 0.97, is_valid_pt_tax_id),
    ("ORGANIZACAO", COMPANY_SUFFIX_RE.pattern, 0.98, None),
    ("TELEFONE", r"\b(?:\+351\s?)?(?:9[1236]\d\s?\d{3}\s?\d{3}|2\d\s?\d{3}\s?\d{3})\b", 0.95, None),
    ("NIF", r"\b(?:N\.?\s*I\.?\s*F\.?\s*)?[1235689]\d{2}\s?\d{3}\s?\d{3}\b", 0.85, is_valid_pt_tax_id),
    ("IBAN", r"\bPT50\s?(?:\d{4}\s?){5}\d\b", 0.9, is_valid_iban),
    ("PROCESSO", r"\b(?:Processo\s+n\.?\s*(?:o|º)\s*)?\d{1,7}/\d{2}\.[A-Z0-9]{1,6}(?:-[A-Z0-9]{1,6})?\b", 0.9, None),
    ("CEDULA_PROFISSIONAL", r"\bC[eé]dula\s+profissional\s+n\.?\s*(?:o|º)\s*\d{1,7}[A-Z]?\b", 0.9, None),
    ("CODIGO_POSTAL", r"\b\d{4}-\d{3}\b", 0.75, None),
    ("CARTAO_CREDITO", r"\b(?:\d[ -]*?){13,19}\b", 0.65, is_valid_luhn),
    ("PESSOA", rf"\b(?:Dr\.?|Dra\.?|Eng\.?[ªº]?|Prof\.?[ªº]?|Advog\.?|Avog\.?)\s+[{UPPER_PT}][{LOWER_PT}]+(?:\s+[{UPPER_PT}][{LOWER_PT}]+)+\b", 0.95, None),
]
