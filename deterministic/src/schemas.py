"""Dataclasses for the deterministic extraction pipeline."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FieldResult:
    """A single extracted financial field."""

    value: float
    scale: str = "raw"  # raw | thousands | millions | billions
    source_filing: str = ""
    source_location: str = ""  # e.g. "table:income_statement:row3"
    confidence: str = "high"  # high | medium | low


@dataclass
class PeriodResult:
    """Extraction results for a single fiscal period."""

    fecha_fin: str = ""  # ISO date, e.g. "2024-12-31"
    tipo_periodo: str = ""  # anual | trimestral | semestral
    fields: Dict[str, FieldResult] = field(default_factory=dict)


@dataclass
class AuditRecord:
    """Audit trail for extraction decisions."""

    fields_extracted: int = 0
    fields_discarded: int = 0
    discarded_reasons: List[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Full extraction result for a case."""

    schema_version: str = "1.0"
    ticker: str = ""
    currency: str = "USD"
    extraction_date: str = field(
        default_factory=lambda: dt.date.today().isoformat()
    )
    filings_used: int = 0
    periods: Dict[str, PeriodResult] = field(default_factory=dict)
    audit: AuditRecord = field(default_factory=AuditRecord)

    def to_dict(self) -> Dict[str, Any]:
        periods_dict: Dict[str, Any] = {}
        for period_key, period in self.periods.items():
            fields_dict: Dict[str, Any] = {}
            for fname, fr in period.fields.items():
                fields_dict[fname] = {
                    "value": fr.value,
                    "scale": fr.scale,
                    "source_filing": fr.source_filing,
                    "source_location": fr.source_location,
                    "confidence": fr.confidence,
                }
            periods_dict[period_key] = {
                "fecha_fin": period.fecha_fin,
                "tipo_periodo": period.tipo_periodo,
                "fields": fields_dict,
            }
        return {
            "schema_version": self.schema_version,
            "ticker": self.ticker,
            "currency": self.currency,
            "extraction_date": self.extraction_date,
            "filings_used": self.filings_used,
            "periods": periods_dict,
            "audit": {
                "fields_extracted": self.audit.fields_extracted,
                "fields_discarded": self.audit.fields_discarded,
                "discarded_reasons": self.audit.discarded_reasons,
            },
        }


@dataclass
class FilingInfo:
    """Metadata about a single filing from EDGAR."""

    form: str
    filing_date: str
    accession: str
    primary_doc: str

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")


@dataclass
class AcquisitionResult:
    """Result of the acquire phase."""

    ticker: str = ""
    source: str = ""
    cik: Optional[str] = None
    filings_downloaded: int = 0
    filings_failed: int = 0
    filings_coverage_pct: float = 0.0
    coverage: Dict[str, Any] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)
    notes: str = ""
    download_date: str = field(
        default_factory=lambda: dt.date.today().isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "source": self.source,
            "cik": self.cik,
            "filings_expected": {
                "annual": {
                    "target": 6,
                    "reason": "<=6 annual (10-K/20-F) per SEC selection policy",
                },
                "quarterly": {
                    "target": 12,
                    "reason": "<=12 quarterly (10-Q/6-K)",
                },
                "earnings": {
                    "target": 10,
                    "reason": "<=10 earnings (8-K with Exhibit 99)",
                },
            },
            "filings_downloaded": self.filings_downloaded,
            "filings_failed": self.filings_failed,
            "filings_coverage_pct": self.filings_coverage_pct,
            "coverage": self.coverage,
            "gaps": self.gaps,
            "notes": self.notes,
            "download_date": self.download_date,
        }


@dataclass
class EvalMatch:
    """A single field comparison result."""

    field_name: str
    period: str
    expected: float
    actual: Optional[float] = None
    status: str = "missed"  # matched | wrong | missed


@dataclass
class EvalReport:
    """Result of evaluating extraction against expected.json."""

    ticker: str = ""
    total_expected: int = 0
    matched: int = 0
    wrong: int = 0
    missed: int = 0
    extra: int = 0
    score: float = 0.0
    filings_coverage_pct: float = 0.0
    required_fields_coverage_pct: float = 0.0
    details: List[EvalMatch] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "total_expected": self.total_expected,
            "matched": self.matched,
            "wrong": self.wrong,
            "missed": self.missed,
            "extra": self.extra,
            "score": round(self.score, 4),
            "filings_coverage_pct": round(self.filings_coverage_pct, 2),
            "required_fields_coverage_pct": round(
                self.required_fields_coverage_pct, 2
            ),
        }


@dataclass
class DashboardRow:
    """A single row in the dashboard report."""

    ticker: str
    source: str
    filings: int
    periods: int
    expected: int
    matched: int
    score: float


@dataclass
class DashboardReport:
    """Aggregate dashboard over all cases."""

    rows: List[DashboardRow] = field(default_factory=list)
    total_filings: int = 0
    total_periods: int = 0
    total_expected: int = 0
    total_matched: int = 0
    total_score: float = 0.0
# test
