"""NLP tokenizer for BOM line raw text per GAP-035, WF-NORM-001 step 2."""
import re
from dataclasses import dataclass


@dataclass
class Token:
    token_type: str
    value: str
    raw_span: tuple[int, int]
    normalized_value: str | None = None

    def to_dict(self) -> dict:
        return {
            "token_type": self.token_type,
            "value": self.value,
            "raw_span": list(self.raw_span),
            "normalized_value": self.normalized_value,
        }


TOKEN_EXTRACTORS: dict[str, re.Pattern] = {
    "value_unit_pair": re.compile(
        r"(\d+(?:\.\d+)?)\s*(k|M|G|µ|u|m|p|n)?\s*"
        r"(ohm|Ω|F|H|V|A|W|Hz|mm|cm|in|m|kg|g|lb|oz)\b",
        re.I,
    ),
    "dimension": re.compile(
        r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)"
        r"(?:\s*[xX×]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|in)?",
        re.I,
    ),
    "tolerance": re.compile(r"[±]\s*[\d.]+\s*(?:mm|in|thou|µm|%)?", re.I),
    "thread_spec": re.compile(
        r"\b(M\d+(?:\.\d+)?(?:\s*[xX]\s*\d+(?:\.\d+)?)?)\b", re.I
    ),
    "part_number_fragment": re.compile(r"\b[A-Z]{2,5}[-]?\d{3,}[A-Z0-9\-]*\b"),
    "package_type": re.compile(
        r"\b(0201|0402|0603|0805|1206|1210|2512|"
        r"SOT-\d+|QFP-\d+|BGA-\d+|DIP-\d+|SOP-\d+|TSSOP-\d+|QFN-\d+)\b",
        re.I,
    ),
    "material_reference": re.compile(
        r"\b(stainless\s*steel|aluminum|copper|brass|titanium|nylon|abs|"
        r"polycarbonate|peek|carbon\s*fiber|steel|inconel|hdpe|ptfe|"
        r"ss\s*304|ss\s*316|ss304|ss316)\b",
        re.I,
    ),
    "finish_reference": re.compile(
        r"\b(anodized|anodizing|plated|painted|powder\s*coat(?:ed)?|"
        r"chrome|polished|galvanized|zinc\s*plated|black\s*oxide|passivated)\b",
        re.I,
    ),
    "grade_reference": re.compile(
        r"\b(?:grade|class)\s*[:=]?\s*(\d+(?:\.\d+)?)\b", re.I
    ),
}


def tokenize_raw_text(raw_text: str) -> list[Token]:
    """Extract structured tokens from raw BOM text."""
    if not raw_text or not raw_text.strip():
        return []
    tokens: list[Token] = []
    for token_type, pattern in TOKEN_EXTRACTORS.items():
        for match in pattern.finditer(raw_text):
            tokens.append(
                Token(
                    token_type=token_type,
                    value=match.group(0),
                    raw_span=(match.start(), match.end()),
                )
            )
    tokens.sort(key=lambda t: t.raw_span[0])
    return tokens
