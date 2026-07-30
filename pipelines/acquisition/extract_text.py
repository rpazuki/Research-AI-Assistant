"""Turn an acquired asset into section-labelled text.

JATS is preferred over PDF wherever the ladder can get it, and this module is
where that preference is justified rather than asserted: `character_fidelity`
measures whether the characters that carry meaning in this domain survived.

`Po1g-Δku70` and `ΔEYD` are strain names. A PDF extractor that renders Δ as `D`,
`?` or drops it produces `Po1g-Dku70`, which is a different strain — and no
downstream reader can tell it was corrupted. Greek letters also carry units
(`μmol`, `°C`) and gene nomenclature (`α-amylase`).

Sections matter because extraction is restricted to Methods and Results: an
Introduction reporting someone else's 488.7 mg/L, attributed to this paper's
authors, is a wrong datasheet row.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Canonical section labels. Everything a journal calls a section maps onto one of
# these, and `other` is honest rather than a guess.
SECTION_TITLE = "title"
SECTION_ABSTRACT = "abstract"
SECTION_INTRO = "introduction"
SECTION_METHODS = "methods"
SECTION_RESULTS = "results"
SECTION_DISCUSSION = "discussion"
SECTION_CONCLUSION = "conclusion"
SECTION_SUPPLEMENTARY = "supplementary"
SECTION_OTHER = "other"

_SECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (SECTION_METHODS, re.compile(r"\b(materials?\s+and\s+methods?|methods?|experimental|methodology)\b", re.I)),
    (SECTION_RESULTS, re.compile(r"\bresults?\b", re.I)),
    (SECTION_DISCUSSION, re.compile(r"\bdiscussion\b", re.I)),
    (SECTION_CONCLUSION, re.compile(r"\b(conclusions?|concluding remarks)\b", re.I)),
    (SECTION_INTRO, re.compile(r"\b(introduction|background)\b", re.I)),
    (SECTION_ABSTRACT, re.compile(r"\babstract\b", re.I)),
    (SECTION_SUPPLEMENTARY, re.compile(r"\b(supplementary|supporting information|appendix)\b", re.I)),
)

# Characters whose loss silently changes meaning in this domain.
CRITICAL_CHARACTERS = "ΔδΑαΒβΓγΕεΘθΚκΛλΜμΝνΠπΡρΣσΤτΦφΧχΨψΩω°±×·′″≥≤→"
_MOJIBAKE = re.compile(r"[�]")


@dataclass
class Section:
    label: str
    heading: str | None
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ExtractedDocument:
    source_format: str
    title: str | None = None
    abstract: str | None = None
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(
            f"## {section.heading or section.label}\n{section.text}" for section in self.sections
        )

    @property
    def all_text(self) -> str:
        """Everything extracted, title included.

        Fidelity is measured over this rather than `full_text`: strain names appear
        in titles at least as often as in bodies (`Engineering Po1g-Δku70 for ...`),
        and a check that skipped the title would pass a document whose most
        prominent Δ had been transliterated away.
        """
        return "\n\n".join(part for part in (self.title, self.full_text) if part)

    @property
    def char_count(self) -> int:
        return sum(section.char_count for section in self.sections)

    def section_text(self, *labels: str) -> str:
        return "\n\n".join(
            section.text for section in self.sections if section.label in labels
        )

    def labels(self) -> list[str]:
        return sorted({section.label for section in self.sections})


def classify_heading(heading: str | None) -> str:
    if not heading:
        return SECTION_OTHER
    for label, pattern in _SECTION_PATTERNS:
        if pattern.search(heading):
            return label
    return SECTION_OTHER


def _node_text(node: ET.Element) -> str:
    """Flatten a JATS node, keeping inline markup's content.

    `<italic>Y. lipolytica</italic>` and `<sub>2</sub>` carry meaning; dropping
    them silently rewrites organism names and chemical formulae.
    """
    parts: list[str] = []
    for chunk in node.itertext():
        cleaned = chunk.strip("\n")
        if cleaned:
            parts.append(cleaned)
    return re.sub(r"[ \t]+", " ", " ".join(parts)).strip()


def extract_jats(xml_bytes: bytes) -> ExtractedDocument:
    """Parse JATS XML into labelled sections."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        return ExtractedDocument(source_format="xml", warnings=[f"unparseable XML: {exc}"])

    document = ExtractedDocument(source_format="xml")

    title_node = root.find(".//title-group/article-title")
    document.title = _node_text(title_node) if title_node is not None else None

    abstract_node = root.find(".//abstract")
    if abstract_node is not None:
        document.abstract = _node_text(abstract_node)
        document.sections.append(
            Section(SECTION_ABSTRACT, "Abstract", document.abstract)
        )

    body = root.find(".//body")
    if body is None:
        document.warnings.append("JATS has no <body>: metadata only")
        return document

    for section_node in body.findall("./sec"):
        heading_node = section_node.find("./title")
        heading = _node_text(heading_node) if heading_node is not None else None
        text = _node_text(section_node)
        if heading and text.startswith(heading):
            text = text[len(heading) :].strip()
        if not text:
            continue
        document.sections.append(Section(classify_heading(heading), heading, text))

    if not document.sections or all(
        section.label == SECTION_ABSTRACT for section in document.sections
    ):
        # Some publishers deposit an unsectioned body.
        text = _node_text(body)
        if text:
            document.sections.append(Section(SECTION_OTHER, None, text))
            document.warnings.append("JATS body has no <sec> structure")

    return document


def extract_pdf(pdf_bytes: bytes) -> ExtractedDocument:
    """Text from a PDF, with headings inferred from line shape.

    Deliberately simple: pypdf is already a dependency, and the S4 spike measures
    whether this is good enough or whether GROBID is worth the operational cost.
    """
    try:
        import io

        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is a declared dependency
        return ExtractedDocument(source_format="pdf", warnings=["pypdf not installed"])

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - a malformed PDF must not kill a run
        return ExtractedDocument(source_format="pdf", warnings=[f"unreadable PDF: {exc}"])

    document = ExtractedDocument(source_format="pdf")
    text = "\n".join(pages)
    if not text.strip():
        document.warnings.append("no extractable text: likely a scanned PDF, needs OCR")
        return document

    # Split on lines that look like headings: short, title-ish, and matching a
    # known section name. Anything else stays in the current section.
    current_label, current_heading, buffer = SECTION_OTHER, None, []
    for line in text.splitlines():
        stripped = line.strip()
        looks_like_heading = (
            0 < len(stripped) <= 60
            and classify_heading(stripped) != SECTION_OTHER
            and not stripped.endswith(".")
        )
        if looks_like_heading:
            if buffer:
                document.sections.append(
                    Section(current_label, current_heading, "\n".join(buffer).strip())
                )
                buffer = []
            current_label, current_heading = classify_heading(stripped), stripped
            continue
        if stripped:
            buffer.append(stripped)

    if buffer:
        document.sections.append(Section(current_label, current_heading, "\n".join(buffer).strip()))

    if all(section.label == SECTION_OTHER for section in document.sections):
        document.warnings.append("no section headings recognised in the PDF text")

    return document


def extract(content: bytes, content_format: str) -> ExtractedDocument:
    """Dispatch on the format the ladder recorded."""
    if content_format == "xml":
        return extract_jats(content)
    if content_format == "pdf":
        return extract_pdf(content)
    return ExtractedDocument(
        source_format=content_format or "unknown",
        warnings=[f"no extractor for format '{content_format}'"],
    )


@dataclass
class FidelityReport:
    """Did the characters that carry meaning survive extraction?"""

    critical_characters: int
    replacement_characters: int
    delta_count: int
    mu_count: int
    suspicious_strain_names: list[str] = field(default_factory=list)
    normalisation_changes: int = 0

    @property
    def looks_corrupted(self) -> bool:
        return bool(self.replacement_characters or self.suspicious_strain_names)

    def as_dict(self) -> dict:
        return {
            "critical_characters": self.critical_characters,
            "replacement_characters": self.replacement_characters,
            "delta_count": self.delta_count,
            "mu_count": self.mu_count,
            "suspicious_strain_names": self.suspicious_strain_names,
            "normalisation_changes": self.normalisation_changes,
            "looks_corrupted": self.looks_corrupted,
        }


# `Po1g-Dku70` is what a Δ-losing extractor produces from `Po1g-Δku70`. Also catch
# a spelled-out "delta" immediately before a gene name.
_TRANSLITERATED_STRAIN = re.compile(
    r"\b(?:Po1[a-z]|W29|A101|H222|JMY\d+)[- ]?D[a-z]{2,}\d*"
    r"|(?<![A-Za-z])delta\s?(?:ku70|eyd|pox|mfe)\d*",
    re.I,
)


def character_fidelity(text: str) -> FidelityReport:
    """Measure Greek-character survival in extracted text.

    Used by S4 to decide route preference on evidence: a route that loses Δ is not
    an acceptable source for strain names, whatever else it does well.
    """
    critical = sum(1 for char in text if char in CRITICAL_CHARACTERS)
    normalised = unicodedata.normalize("NFKC", text)
    return FidelityReport(
        critical_characters=critical,
        replacement_characters=len(_MOJIBAKE.findall(text)),
        delta_count=text.count("Δ") + text.count("δ"),
        mu_count=text.count("μ") + text.count("µ"),
        suspicious_strain_names=sorted({match.group(0) for match in _TRANSLITERATED_STRAIN.finditer(text)}),
        normalisation_changes=sum(1 for a, b in zip(text, normalised) if a != b),
    )
