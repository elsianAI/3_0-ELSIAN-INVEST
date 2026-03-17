"""Importa truth packs legacy y los adapta al flujo operativo del engine."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.runners.tp_calculator import calculate as calculate_truthpack
from scripts.runners.tp_validator import validate as validate_truthpack

from .state import SUB_STEPS, init_or_load_state, read_modify_write
from .validator import validate_partial_truthpack


_LEGACY_TO_CANONICAL = {
	"ingresos": "ingresos_usd",
	"cost_of_revenue": "cogs_usd",
	"gross_profit": "gross_profit_usd",
	"ebitda": "ebitda_usd",
	"ebit": "ebit_usd",
	"net_income": "net_income_usd",
	"cfo": "cfo_usd",
	"cfi": "cfi_usd",
	"cff": "cff_usd",
	"capex": "capex_usd",
	"delta_cash": "delta_cash_usd",
	"depreciation_amortization": "depreciation_usd",
	"income_tax": "income_tax_usd",
	"interest_expense": "interest_expense_usd",
	"pretax_income": "pretax_income_usd",
	"interest_expense_net": "interest_expense_net_usd",
	"loss_on_sale_of_businesses": "loss_on_sale_of_businesses_usd",
	"gain_on_investments_net": "gain_on_investments_net_usd",
	"provision_credit_losses_investments": "provision_credit_losses_investments_usd",
	"other_loss_income_net": "other_loss_income_net_usd",
	"research_and_development": "rd_usd",
	"sga": "sga_usd",
	"cash_and_equivalents": "caja_usd",
	"total_assets": "activos_totales_usd",
	"total_liabilities": "pasivos_totales_usd",
	"total_equity": "patrimonio_usd",
	"accounts_receivable_total": "accounts_receivable_total_usd",
	"trade_receivables": "trade_receivables_net_usd",
	"settlement_receivables": "settlement_receivables_net_usd",
	"other_receivables": "other_receivables_usd",
	"eps_basic": "eps_basic",
	"eps_diluted": "eps_diluted",
	"shares_outstanding": "acciones_diluidas",
	"shares_outstanding_end": "shares_outstanding_end",
	"weighted_avg_basic": "weighted_avg_basic",
	"weighted_avg_diluted": "weighted_avg_diluted",
}

_BALANCE_FIELDS = {
	"activos_totales_usd",
	"pasivos_totales_usd",
	"patrimonio_usd",
	"caja_usd",
}

_MONETARY_FIELDS = {
	key
	for key in _LEGACY_TO_CANONICAL
	if key not in {"eps_basic", "eps_diluted", "shares_outstanding"}
}

_RAW_THOUSANDS_HEURISTIC_FIELDS = _MONETARY_FIELDS

_UNIT_FAMILY_RAW_FIELDS = {
	"shares_outstanding",
	"shares_outstanding_end",
	"weighted_avg_basic",
	"weighted_avg_diluted",
	"eps_basic",
	"eps_diluted",
	"dividends_per_share",
}

_LEGACY_REVIEW_REQUIRED_FIELDS = {
	"shares_outstanding_end",
	"weighted_avg_basic",
	"weighted_avg_diluted",
	"eps_basic",
	"eps_diluted",
	"dividends_per_share",
	"pretax_income_usd",
	"interest_expense_net_usd",
	"loss_on_sale_of_businesses_usd",
	"gain_on_investments_net_usd",
	"provision_credit_losses_investments_usd",
	"other_loss_income_net_usd",
	"trade_receivables_net_usd",
	"settlement_receivables_net_usd",
	"other_receivables_usd",
}

_PERIOD_OVERRIDE_FIELD_MAP = {
	"shares_outstanding_end": "shares_outstanding_end",
	"weighted_avg_basic": "weighted_avg_basic",
	"weighted_avg_diluted": "weighted_avg_diluted",
	"trade_receivables_net_usd": "trade_receivables_net_usd",
	"settlement_receivables_net_usd": "settlement_receivables_net_usd",
	"other_receivables_usd": "other_receivables_usd",
	"allowance_credit_losses_ar_usd": "allowance_credit_losses_ar_usd",
	"pretax_income_usd": "pretax_income_usd",
	"interest_expense_net_usd": "interest_expense_net_usd",
	"loss_on_sale_of_businesses_usd": "loss_on_sale_of_businesses_usd",
	"gain_on_investments_net_usd": "gain_on_investments_net_usd",
	"provision_credit_losses_investments_usd": "provision_credit_losses_investments_usd",
	"other_loss_income_net_usd": "other_loss_income_net_usd",
	"fcf_reported_fy2025_usd": "fcf_reported_fy2025_usd",
	"fcf_adjusted_ex_tds_wc_fy2025_usd": "fcf_adjusted_ex_tds_wc_fy2025_usd",
}

_SCALE_MULTIPLIERS = {
	"raw": 1.0,
	"unit": 1.0,
	"units": 1.0,
	"1": 1.0,
	"thousand": 1_000.0,
	"thousands": 1_000.0,
	"k": 1_000.0,
	"miles": 1_000.0,
	"million": 1_000_000.0,
	"millions": 1_000_000.0,
	"m": 1_000_000.0,
	"millones": 1_000_000.0,
	"billion": 1_000_000_000.0,
	"billions": 1_000_000_000.0,
	"bn": 1_000_000_000.0,
	"billones": 1_000_000_000.0,
}

_ROOT_METADATA_FIELDS = (
	"company_name",
	"exchange",
	"country",
	"sector",
	"industry",
)

_PERIOD_TYPE_NORMALIZATION = {
	"annual": "anual",
	"fy": "anual",
	"anual": "anual",
	"quarterly": "trimestral",
	"quarter": "trimestral",
	"trimestral": "trimestral",
	"h1": "semestral",
	"half_year": "semestral",
	"half-year": "semestral",
	"semiannual": "semestral",
	"semestral": "semestral",
	"9m": "nine_months",
	"nine_months": "nine_months",
	"nine-months": "nine_months",
}


def diagnose_legacy_truthpack_payload(payload: dict[str, Any]) -> dict[str, Any]:
	"""Diagnostica si un truth pack legacy es importable, reparable o bloqueado."""
	issues: list[dict[str, Any]] = []
	auto_fixable: list[str] = []
	required_upstream_data: list[str] = []

	if not isinstance(payload, dict):
		return {
			"status": "blocked",
			"issues": [
				{
					"severity": "error",
					"code": "INVALID_PAYLOAD_TYPE",
					"message": "El truth_pack de origen no es un objeto JSON válido.",
					"path": "$",
				}
			],
			"auto_fixable": [],
			"required_upstream_data": ["truth_pack.json válido"],
		}

	financial_data = payload.get("financial_data")
	if not isinstance(financial_data, dict) or not financial_data:
		issues.append(
			{
				"severity": "error",
				"code": "MISSING_FINANCIAL_DATA",
				"message": "Falta financial_data o no contiene periodos utilizables.",
				"path": "financial_data",
			}
		)
		required_upstream_data.append("financial_data con al menos un periodo y fields extraíbles")
	else:
		usable_periods = 0
		for period_name, period_payload in financial_data.items():
			if not isinstance(period_payload, dict):
				continue
			fields = period_payload.get("fields")
			if not isinstance(fields, dict) or not fields:
				issues.append(
					{
						"severity": "warning",
						"code": "EMPTY_PERIOD_FIELDS",
						"message": f"El periodo {period_name} no contiene fields utilizables.",
						"path": f"financial_data.{period_name}.fields",
					}
				)
				continue
			has_value = False
			for item in fields.values():
				if isinstance(item, dict) and item.get("value") is not None:
					has_value = True
					break
			if has_value:
				usable_periods += 1
			else:
				issues.append(
					{
						"severity": "warning",
						"code": "PERIOD_WITHOUT_VALUES",
						"message": f"El periodo {period_name} no tiene valores numéricos utilizables.",
						"path": f"financial_data.{period_name}",
					}
				)

			inferred = _infer_period_metadata(period_name, payload)
			current_fecha = period_payload.get("fecha_fin")
			current_tipo = _normalized_period_type(period_payload.get("tipo_periodo"))
			if inferred is not None:
				if not current_fecha:
					issues.append(
						{
							"severity": "warning",
							"code": "MISSING_PERIOD_END_DATE",
							"message": f"El periodo {period_name} no tiene fecha_fin y puede inferirse automáticamente.",
							"path": f"financial_data.{period_name}.fecha_fin",
						}
					)
					auto_fixable.append(f"infer_fecha_fin:{period_name}")
				if not current_tipo or current_tipo == "unknown":
					issues.append(
						{
							"severity": "warning",
							"code": "MISSING_PERIOD_TYPE",
							"message": f"El periodo {period_name} no tiene tipo_periodo fiable y puede inferirse automáticamente.",
							"path": f"financial_data.{period_name}.tipo_periodo",
						}
					)
					auto_fixable.append(f"infer_tipo_periodo:{period_name}")
			elif not current_fecha or not current_tipo or current_tipo == "unknown":
				issues.append(
					{
						"severity": "warning",
						"code": "NON_INFERABLE_PERIOD_METADATA",
						"message": f"El periodo {period_name} tiene metadatos incompletos y no puede inferirse con seguridad.",
						"path": f"financial_data.{period_name}",
					}
				)

		if usable_periods == 0:
			issues.append(
				{
					"severity": "error",
					"code": "NO_USABLE_PERIODS",
					"message": "financial_data existe pero no contiene periodos con values utilizables.",
					"path": "financial_data",
				}
			)
			required_upstream_data.append("Al menos un periodo con fields.*.value")

	sources = payload.get("sources")
	if isinstance(sources, dict):
		if isinstance(payload.get("financial_data"), dict) and payload.get("financial_data"):
			extraction_source = str(sources.get("extraction_result") or "").strip()
			if extraction_source and not extraction_source.startswith("embedded:"):
				issues.append(
					{
						"severity": "warning",
						"code": "NON_EMBEDDED_EXTRACTION_SOURCE",
						"message": "sources.extraction_result no está autocontenido y puede normalizarse a embedded:financial_data.",
						"path": "sources.extraction_result",
					}
				)
				auto_fixable.append("sources:extraction_result->embedded:financial_data")
		market_data_source = str(sources.get("market_data") or "").strip()
		if isinstance(payload.get("market_data"), dict) and market_data_source and not market_data_source.startswith("embedded:"):
			issues.append(
				{
					"severity": "warning",
					"code": "NON_EMBEDDED_MARKET_SOURCE",
					"message": "sources.market_data no está autocontenido y puede normalizarse a embedded:market_data.",
					"path": "sources.market_data",
				}
			)
			auto_fixable.append("sources:market_data->embedded:market_data")

	market_data = payload.get("market_data")
	if not isinstance(market_data, dict):
		issues.append(
			{
				"severity": "warning",
				"code": "MISSING_MARKET_DATA",
				"message": "No hay market_data embebido; la importación puede continuar, pero mercado y EV quedarán incompletos si no existe sidecar.",
				"path": "market_data",
			}
		)
	else:
		for key in _ROOT_METADATA_FIELDS:
			if not payload.get(key) and market_data.get(key):
				issues.append(
					{
						"severity": "warning",
						"code": f"MISSING_ROOT_{key.upper()}",
						"message": f"{key} falta en raíz pero está disponible en market_data y puede elevarse automáticamente.",
						"path": key,
					}
				)
				auto_fixable.append(f"lift_root_metadata:{key}")

		unit_issue = _diagnose_embedded_market_units(market_data)
		if unit_issue is not None:
			issues.append(unit_issue)
			auto_fixable.append("normalize_market_data_units")

	has_error = any(issue.get("severity") == "error" for issue in issues)
	status = "blocked" if has_error else "reparable" if auto_fixable else "importable"

	return {
		"status": status,
		"issues": issues,
		"auto_fixable": sorted(set(auto_fixable)),
		"required_upstream_data": sorted(set(required_upstream_data)),
	}


def normalize_legacy_truthpack_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
	"""Normaliza un truth pack legacy sin mutar el payload de entrada."""
	normalized = deepcopy(payload)
	applied_fixes: list[str] = []

	market_data = normalized.get("market_data")
	if isinstance(market_data, dict):
		for key in _ROOT_METADATA_FIELDS:
			if not normalized.get(key) and market_data.get(key):
				normalized[key] = market_data.get(key)
				applied_fixes.append(f"lift_root_metadata:{key}")

		normalized_market_data, market_fixes = _normalize_embedded_market_data(market_data)
		normalized["market_data"] = normalized_market_data
		applied_fixes.extend(market_fixes)

	sources = normalized.get("sources")
	if isinstance(sources, dict):
		if isinstance(normalized.get("financial_data"), dict) and normalized.get("financial_data"):
			extraction_source = str(sources.get("extraction_result") or "").strip()
			if not extraction_source or not extraction_source.startswith("embedded:"):
				sources["extraction_result"] = "embedded:financial_data"
				applied_fixes.append("sources:extraction_result->embedded:financial_data")
		if isinstance(normalized.get("market_data"), dict):
			market_source = str(sources.get("market_data") or "").strip()
			if not market_source or not market_source.startswith("embedded:"):
				sources["market_data"] = "embedded:market_data"
				applied_fixes.append("sources:market_data->embedded:market_data")

	financial_data = normalized.get("financial_data")
	if isinstance(financial_data, dict):
		for period_name, period_payload in financial_data.items():
			if not isinstance(period_payload, dict):
				continue
			inferred = _infer_period_metadata(period_name, normalized)
			if inferred is None:
				continue
			fecha_fin, tipo_periodo = inferred
			if not period_payload.get("fecha_fin"):
				period_payload["fecha_fin"] = fecha_fin
				applied_fixes.append(f"infer_fecha_fin:{period_name}")
			current_tipo = _normalized_period_type(period_payload.get("tipo_periodo"))
			if not current_tipo or current_tipo == "unknown":
				period_payload["tipo_periodo"] = tipo_periodo
				applied_fixes.append(f"infer_tipo_periodo:{period_name}")

	diagnosis = diagnose_legacy_truthpack_payload(normalized)
	normalized["_legacy_normalization"] = {
		"applied_fixes": sorted(set(applied_fixes)),
		"normalized_at_utc": datetime.now(timezone.utc).isoformat(),
		"diagnosis_after_normalization": diagnosis,
	}
	return normalized, normalized["_legacy_normalization"]


def _format_legacy_truthpack_diagnosis(diagnosis: dict[str, Any]) -> str:
	status = str(diagnosis.get("status") or "unknown")
	issues = diagnosis.get("issues") or []
	required = diagnosis.get("required_upstream_data") or []
	parts = [f"Diagnóstico legacy truth_pack: status={status}"]
	for issue in issues[:5]:
		severity = str(issue.get("severity") or "warning").upper()
		message = str(issue.get("message") or "")
		parts.append(f"[{severity}] {message}")
	if required:
		parts.append("Datos requeridos: " + ", ".join(str(item) for item in required))
	return "; ".join(parts)


def _diagnose_embedded_market_units(market_data: dict[str, Any]) -> dict[str, Any] | None:
	market_cap = _to_float(market_data.get("market_cap"))
	shares = _to_float(market_data.get("shares_outstanding"))
	price = _to_float(market_data.get("price"))
	market_cap_m = _to_float(market_data.get("market_cap_millions"))
	shares_m = _to_float(market_data.get("shares_outstanding_millions"))

	if market_cap is not None and market_cap_m is not None and abs(market_cap - (market_cap_m * 1_000_000.0)) < 1.0:
		return None
	if shares is not None and shares_m is not None and abs(shares - (shares_m * 1_000_000.0)) < 1.0:
		return None
	if market_cap_m is not None or shares_m is not None:
		return None
	if market_cap is None or shares is None or price is None:
		return None
	if market_cap >= 10_000_000 or shares >= 1_000_000:
		return None
	if abs((shares * price) - market_cap) / max(market_cap, 1.0) > 0.25:
		return None
	return {
		"severity": "warning",
		"code": "LIKELY_MARKET_DATA_IN_MILLIONS",
		"message": "market_data parece expresado en millones y puede normalizarse a unidades absolutas.",
		"path": "market_data",
	}


def _normalize_embedded_market_data(market_data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
	normalized = deepcopy(market_data)
	applied: list[str] = []

	market_cap = _to_float(normalized.get("market_cap"))
	shares = _to_float(normalized.get("shares_outstanding"))
	market_cap_m = _to_float(normalized.get("market_cap_millions"))
	shares_m = _to_float(normalized.get("shares_outstanding_millions"))
	price = _to_float(normalized.get("price"))

	if market_cap is None and market_cap_m is not None:
		normalized["market_cap"] = market_cap_m * 1_000_000.0
		applied.append("market_data:market_cap_from_millions")
	elif market_cap is not None and market_cap_m is None and market_cap < 10_000_000 and price is not None:
		if shares is not None and shares < 1_000_000 and abs((shares * price) - market_cap) / max(market_cap, 1.0) <= 0.25:
			normalized["market_cap_millions"] = market_cap
			normalized["market_cap"] = market_cap * 1_000_000.0
			applied.append("market_data:market_cap_to_absolute")

	if shares is None and shares_m is not None:
		normalized["shares_outstanding"] = shares_m * 1_000_000.0
		applied.append("market_data:shares_from_millions")
	elif shares is not None and shares_m is None and shares < 1_000_000 and market_cap is not None and price is not None:
		if abs((shares * price) - market_cap) / max(market_cap, 1.0) <= 0.25:
			normalized["shares_outstanding_millions"] = shares
			normalized["shares_outstanding"] = shares * 1_000_000.0
			applied.append("market_data:shares_to_absolute")

	if applied:
		normalized["normalization_note"] = (
			"market_cap and shares_outstanding normalized to absolute units for engine import compatibility"
		)
	return normalized, applied


def _normalized_period_type(value: Any) -> str | None:
	if value is None:
		return None
	text = str(value).strip().lower()
	if not text:
		return None
	return _PERIOD_TYPE_NORMALIZATION.get(text, text)


def _infer_period_metadata(period_name: str, payload: dict[str, Any]) -> tuple[str, str] | None:
	period = str(period_name or "").strip()
	if not period:
		return None
	fiscal_year_end_month = int(payload.get("metadata", {}).get("fiscal_year_end_month") or 12)
	if fiscal_year_end_month != 12:
		fy_match = re.match(r"^FY(\d{4})$", period)
		if fy_match:
			year = int(fy_match.group(1))
			return _format_month_end(year, fiscal_year_end_month), "anual"
		return None

	fy_match = re.match(r"^FY(\d{4})$", period)
	if fy_match:
		year = int(fy_match.group(1))
		return f"{year}-12-31", "anual"

	quarter_match = re.match(r"^Q([1-4])-(\d{4})$", period)
	if quarter_match:
		quarter = int(quarter_match.group(1))
		year = int(quarter_match.group(2))
		quarter_end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[quarter]
		return f"{year}-{quarter_end}", "trimestral"

	h1_match = re.match(r"^H1-(\d{4})$", period)
	if h1_match:
		year = int(h1_match.group(1))
		return f"{year}-06-30", "semestral"

	nine_month_match = re.match(r"^9M-(\d{4})$", period)
	if nine_month_match:
		year = int(nine_month_match.group(1))
		return f"{year}-09-30", "nine_months"

	return None


def _format_month_end(year: int, month: int) -> str:
	if month in {1, 3, 5, 7, 8, 10, 12}:
		day = 31
	elif month in {4, 6, 9, 11}:
		day = 30
	else:
		day = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
	return f"{year}-{month:02d}-{day:02d}"


def import_truthpack_case(
	*,
	case_dir: Path,
	ticker: str,
	date_str: str,
	input_path: Path,
	exchange: str = "",
	country: str = "",
	web_ir: str = "",
	overwrite: bool = False,
) -> Path:
	"""Convierte un truth_pack legacy a TruthPack_v1 y bootstrapea el caso.

	Args:
		case_dir: Carpeta del caso destino.
		ticker: Ticker del caso.
		date_str: Fecha del caso en formato YYYY-MM-DD.
		input_path: Ruta al ``truth_pack.json`` legacy.
		exchange: Hint opcional de bolsa.
		country: Hint opcional de país.
		web_ir: Hint opcional de Investor Relations.
		overwrite: Si ``True``, sobrescribe artefacto/estado importados.

	Returns:
		Ruta del ``TruthPack_v1_{ticker}.json`` generado.
	"""
	payload = json.loads(input_path.read_text(encoding="utf-8"))
	diagnosis = diagnose_legacy_truthpack_payload(payload)
	if diagnosis.get("status") == "blocked":
		raise ValueError(_format_legacy_truthpack_diagnosis(diagnosis))
	if diagnosis.get("status") == "reparable":
		payload, _ = normalize_legacy_truthpack_payload(payload)
	market_data_override = _resolve_market_data_payload(payload.get("market_data"), input_path)
	converted = convert_legacy_truthpack(
		payload,
		ticker=ticker,
		date_str=date_str,
		exchange=exchange,
		country=country,
		source_path=input_path,
		market_data_override=market_data_override,
	)
	output_path = case_dir / f"TruthPack_v1_{ticker}.json"

	if output_path.exists() and not overwrite:
		raise FileExistsError(
			f"{output_path} ya existe. Usa overwrite=True para reemplazarlo."
		)

	case_dir.mkdir(parents=True, exist_ok=True)
	output_path.write_text(
		json.dumps(converted, indent=2, ensure_ascii=False),
		encoding="utf-8",
	)
	_bootstrap_case_state(
		case_dir=case_dir,
		ticker=ticker,
		date_str=date_str,
		artifact_name=output_path.name,
		source_path=input_path,
		exchange=exchange,
		country=country,
		web_ir=web_ir,
	)
	return output_path


def convert_legacy_truthpack(
	payload: dict[str, Any],
	*,
	ticker: str,
	date_str: str,
	exchange: str = "",
	country: str = "",
	source_path: Path | None = None,
	market_data_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Convierte un truth pack legacy al formato operativo del engine."""
	assembly_date = str(payload.get("assembly_date") or date_str)
	financial_data = payload.get("financial_data", {})
	if not isinstance(financial_data, dict) or not financial_data:
		raise ValueError("Legacy truth_pack sin financial_data utilizable")

	annual_entries: list[dict[str, Any]] = []
	quarterly_entries: list[dict[str, Any]] = []
	balance_snapshots: list[dict[str, Any]] = []
	partial_periods: list[str] = []

	for period_name, period_payload in financial_data.items():
		if not isinstance(period_payload, dict):
			continue
		built = _build_period_entry(period_name, period_payload)
		if built is None:
			continue
		bucket = built.pop("_bucket")
		if built.get("_periodo_parcial"):
			partial_periods.append(period_name)

		balance_snapshot = _extract_balance_snapshot(built)
		if balance_snapshot is not None:
			balance_snapshots.append(balance_snapshot)

		if bucket == "annual":
			annual_entries.append(built)
		else:
			quarterly_entries.append(built)

	annual_entries.sort(key=_sort_key)
	quarterly_entries.sort(key=_sort_key)
	balance_snapshots.sort(key=_sort_key)
	balance_latest = balance_snapshots[-1] if balance_snapshots else {}

	latest_fy = annual_entries[-1] if annual_entries else {}
	latest_period = quarterly_entries[-1] if quarterly_entries else latest_fy

	market_data = market_data_override if isinstance(market_data_override, dict) else payload.get("market_data")
	mercado = _build_mercado_block(assembly_date, market_data)

	result: dict[str, Any] = {
		"version_esquema": "TruthPack_v1",
		"schema_version": payload.get("schema_version") or "TruthPack_v1",
		"caso_id": f"CASE_{date_str.replace('-', '')}_{ticker}",
		"ticker": ticker,
		"fecha_corte": assembly_date,
		"empresa": {
			"ticker": ticker,
			"nombre": str(payload.get("company_name") or ticker),
			"bolsa": str(exchange or payload.get("exchange") or "UNKNOWN"),
			"pais": str(country or payload.get("country") or "UNKNOWN"),
			"sector": str(payload.get("sector") or "UNKNOWN"),
			"industria": str(payload.get("industry") or "UNKNOWN"),
		},
		"fuentes_usadas": _build_fuentes_usadas(payload, annual_entries, quarterly_entries),
		"unidades": {
			"moneda_reportada": str(payload.get("currency") or "UNKNOWN"),
			"escala": "1",
			"nota": (
				"Valores normalizados a unidades absolutas USD a partir de scale field-level "
				"del truth_pack legacy, con heurística de miles para valores monetarios/raw."
			),
		},
		"mercado": mercado,
		"historico_anual": annual_entries,
		"historico_trimestral": quarterly_entries,
		"balance_sheet_ultimo": balance_latest,
		"ttm": {
			"periodo": "TTM",
			"fecha_fin": latest_period.get("fecha_fin") or latest_fy.get("fecha_fin") or assembly_date,
			"ingresos_usd": None,
			"ebit_usd": None,
			"cfo_usd": None,
			"capex_usd": None,
			"fcf_usd": None,
			"metodo": "no_disponible",
			"nota": "Pendiente de cálculo/normalización tras importación legacy.",
		},
		"metricas_derivadas": {
			"margen_bruto_pct": None,
			"margen_operativo_pct": None,
			"margen_fcf_pct": None,
			"fcf_yield_pct": None,
			"ev_ebit": None,
			"ev_fcf": None,
			"net_debt_ebitda": None,
			"interest_coverage": None,
			"variacion_acciones_yoy_pct": None,
			"nota": "Inicializado desde importación legacy; se recalcula con tp_calculator.",
		},
		"deuda_y_liquidez": {
			"disponible": False,
			"vencimientos": [],
			"covenants_mencionados": [],
			"notas": "No inferido automáticamente desde truth_pack legacy.",
		},
		"segmentos": {
			"disponible": False,
			"tabla": [],
			"notas": "No inferido automáticamente desde truth_pack legacy.",
		},
		"canonicos_metadata": {
			"periodo_base": _periodo_base_from_legacy(payload),
			"fecha_fin_periodo_base": _legacy_ttm_fecha_fin(payload) or latest_period.get("fecha_fin") or latest_fy.get("fecha_fin"),
			"nota": "Periodo base derivado del truth_pack legacy importado.",
		},
		"operating_lease_liabilities_pv_current": None,
		"operating_lease_liabilities_pv_noncurrent": None,
		"operating_lease_liabilities_pv_total": None,
		"lease_discount_rate": None,
		"lease_remaining_term": None,
		"wc_change_accounts_receivable": _latest_field_value(quarterly_entries, annual_entries, "accounts_receivable"),
		"wc_change_inventories": _latest_field_value(quarterly_entries, annual_entries, "inventories"),
		"wc_change_accounts_payable": _latest_field_value(quarterly_entries, annual_entries, "accounts_payable"),
		"wc_change_other_operating": None,
		"cfo_usd": latest_period.get("cfo_usd") or latest_fy.get("cfo_usd"),
		"ebit_usd": latest_period.get("ebit_usd") or latest_fy.get("ebit_usd"),
		"shares_outstanding_end": latest_period.get("shares_outstanding_end") or latest_fy.get("shares_outstanding_end") or latest_period.get("acciones_diluidas") or latest_fy.get("acciones_diluidas"),
		"weighted_avg_basic": latest_period.get("weighted_avg_basic") or latest_fy.get("weighted_avg_basic") or latest_period.get("acciones_diluidas") or latest_fy.get("acciones_diluidas"),
		"weighted_avg_diluted": latest_period.get("weighted_avg_diluted") or latest_fy.get("weighted_avg_diluted") or latest_period.get("acciones_diluidas") or latest_fy.get("acciones_diluidas"),
		"accounts_receivable_total_usd": latest_period.get("accounts_receivable_total_usd") or latest_fy.get("accounts_receivable_total_usd") or latest_period.get("accounts_receivable") or latest_fy.get("accounts_receivable"),
		"trade_receivables_net_usd": latest_period.get("trade_receivables_net_usd") or latest_fy.get("trade_receivables_net_usd"),
		"settlement_receivables_net_usd": latest_period.get("settlement_receivables_net_usd") or latest_fy.get("settlement_receivables_net_usd"),
		"other_receivables_usd": latest_period.get("other_receivables_usd") or latest_fy.get("other_receivables_usd"),
		"pretax_income_usd": latest_period.get("pretax_income_usd") or latest_fy.get("pretax_income_usd"),
		"interest_expense_net_usd": latest_period.get("interest_expense_net_usd") or latest_fy.get("interest_expense_net_usd"),
		"loss_on_sale_of_businesses_usd": latest_period.get("loss_on_sale_of_businesses_usd") or latest_fy.get("loss_on_sale_of_businesses_usd"),
		"gain_on_investments_net_usd": latest_period.get("gain_on_investments_net_usd") or latest_fy.get("gain_on_investments_net_usd"),
		"provision_credit_losses_investments_usd": latest_period.get("provision_credit_losses_investments_usd") or latest_fy.get("provision_credit_losses_investments_usd"),
		"other_loss_income_net_usd": latest_period.get("other_loss_income_net_usd") or latest_fy.get("other_loss_income_net_usd"),
		"sbc_expense": None,
		"equity_plan_overhang": None,
		"capex_cash_paid": latest_period.get("capex_usd") or latest_fy.get("capex_usd"),
		"ppe_rollforward": None,
		"rou_assets_change": None,
		"capex_maintenance_signal": None,
		"fuente_refs_canonicos": _build_fuente_refs_canonicos(annual_entries, quarterly_entries),
		"data_quality": {
			"status": "PARTIAL",
			"overall_status": "PARTIAL",
			"validaciones": {},
			"confidence_score": None,
			"faltantes_criticos": [],
			"limitaciones": [
				"TruthPack importado desde formato legacy; faltan market data y artefactos SOURCES nativos.",
			],
		},
		"recomendacion_siguiente_paso": {
			"puede_pasar_a_implied_expectations": True,
			"condiciones": [],
		},
		"_legacy_import": {
			"source_file": str(source_path) if source_path else None,
			"imported_at_utc": datetime.now(timezone.utc).isoformat(),
			"legacy_schema_version": payload.get("schema_version"),
			"partial_periods": partial_periods,
			"legacy_quality": payload.get("quality"),
			"legacy_metadata": payload.get("metadata"),
			"legacy_sources": payload.get("sources"),
			"legacy_derived_metrics": payload.get("derived_metrics"),
		},
	}

	calculated = calculate_truthpack(result, market_data if isinstance(market_data, dict) else {})
	calculated = _merge_legacy_metric_fallbacks(calculated, payload)
	override_doc, override_path = _load_case_truthpack_overrides(source_path.parent if source_path else None, ticker)
	if override_doc is not None:
		calculated = _apply_truthpack_critical_overrides(
			calculated,
			override_doc,
			override_path=override_path,
		)
	validated = validate_truthpack(calculated)
	dq = validated.setdefault("data_quality", {})
	legacy_status = _quality_status_from_legacy(payload)
	if dq.get("status") is None:
		dq["status"] = dq.get("overall_status") or legacy_status
	if dq.get("overall_status") is None and dq.get("status") is not None:
		dq["overall_status"] = dq["status"]
	if dq.get("confidence_score") is None:
		legacy_quality = payload.get("quality", {})
		if isinstance(legacy_quality, dict):
			dq["confidence_score"] = legacy_quality.get("confidence_score")
	if legacy_status and dq.get("overall_status") == "FAIL" and legacy_status != "FAIL":
		dq["legacy_validation_status"] = legacy_status
		dq["status"] = legacy_status
		dq["overall_status"] = legacy_status
		dq.setdefault("limitaciones", []).append(
			"data_quality local relajado a favor del estatus del truth_pack legacy importado"
		)
	_apply_legacy_import_policy(
		validated,
		override_doc=override_doc,
		override_path=override_path,
	)
	validated["recomendacion_siguiente_paso"] = {
		"puede_pasar_a_implied_expectations": dq.get("overall_status") != "FAIL",
		"condiciones": dq.get("warnings", [])[:3] if dq.get("overall_status") == "FAIL" else [],
	}

	ok, errors = validate_partial_truthpack(validated)
	if not ok:
		raise ValueError(f"TruthPack importado inválido: {'; '.join(errors)}")

	return validated


def _load_case_truthpack_overrides(
	case_dir: Path | None,
	ticker: str,
) -> tuple[dict[str, Any] | None, Path | None]:
	if case_dir is None:
		return None, None

	candidates = [
		case_dir / f"TruthPack_v1_{ticker}_critical_overrides.json",
		case_dir / f"TruthPack_v1_{ticker.upper()}_critical_overrides.json",
	]
	candidates.extend(sorted(case_dir.glob("TruthPack_v1_*_critical_overrides.json")))

	seen: set[Path] = set()
	for path in candidates:
		if path in seen or not path.exists():
			continue
		seen.add(path)
		try:
			loaded = json.loads(path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			continue
		if isinstance(loaded, dict):
			return loaded, path
	return None, None


def _apply_truthpack_critical_overrides(
	truthpack: dict[str, Any],
	override_doc: dict[str, Any],
	*,
	override_path: Path | None = None,
) -> dict[str, Any]:
	result = deepcopy(truthpack)
	overrides = override_doc.get("overrides")
	base_year = _override_base_year(override_doc)
	applied: list[dict[str, Any]] = []

	if isinstance(overrides, list):
		for item in overrides:
			if not isinstance(item, dict):
				continue
			field_path = str(item.get("campo") or "").strip()
			if not field_path:
				continue
			value = item.get("valor")
			_set_truthpack_value(result, field_path, value)
			_apply_period_level_override(result, field_path, value, base_year=base_year)
			applied.append(
				{
					"campo": field_path,
					"valor": value,
					"justificacion": item.get("justificacion"),
				}
			)

	metricas_doc = override_doc.get("metricas_derivadas")
	if isinstance(metricas_doc, dict) and metricas_doc:
		result.setdefault("metricas_derivadas", {}).update(metricas_doc)

	_derive_override_metrics(result, base_year=base_year)
	result["_critical_overrides"] = {
		"version_esquema": str(override_doc.get("version_esquema") or "TruthPackCriticalOverrides_v1"),
		"source_file": str(override_path) if override_path else None,
		"applied_at_utc": datetime.now(timezone.utc).isoformat(),
		"override_count": len(applied),
		"campos_aplicados": applied,
		"motivo": override_doc.get("motivo"),
		"nota_de_uso": override_doc.get("nota_de_uso"),
	}
	return result


def _override_base_year(override_doc: dict[str, Any]) -> int | None:
	override_years: list[int] = []
	for item in override_doc.get("overrides", []) if isinstance(override_doc.get("overrides"), list) else []:
		if not isinstance(item, dict):
			continue
		field_path = str(item.get("campo") or "")
		match = re.search(r"fy(\d{4})", field_path, flags=re.IGNORECASE)
		if match:
			override_years.append(int(match.group(1)))
	for key in (override_doc.get("metricas_derivadas") or {}).keys() if isinstance(override_doc.get("metricas_derivadas"), dict) else []:
		match = re.search(r"fy(\d{4})", str(key), flags=re.IGNORECASE)
		if match:
			override_years.append(int(match.group(1)))
	if override_years:
		return max(override_years)
	fecha = str(override_doc.get("fecha_corte") or "").strip()
	if re.match(r"^\d{4}-\d{2}-\d{2}$", fecha):
		return int(fecha[:4])
	return None


def _set_truthpack_value(target: dict[str, Any], field_path: str, value: Any) -> None:
	parts = [part for part in field_path.split(".") if part]
	if not parts:
		return
	cursor: dict[str, Any] = target
	for part in parts[:-1]:
		current = cursor.get(part)
		if not isinstance(current, dict):
			current = {}
			cursor[part] = current
		cursor = current
	cursor[parts[-1]] = value


def _apply_period_level_override(
	truthpack: dict[str, Any],
	field_path: str,
	value: Any,
	*,
	base_year: int | None,
) -> None:
	if base_year is None:
		return
	period_field = _PERIOD_OVERRIDE_FIELD_MAP.get(field_path)
	if period_field is None:
		return
	target_period = f"FY{base_year}"
	for entry in truthpack.get("historico_anual", []):
		if isinstance(entry, dict) and entry.get("periodo") == target_period:
			entry[period_field] = value
			if field_path == "weighted_avg_basic":
				entry["acciones_diluidas"] = value
			if field_path in {
				"trade_receivables_net_usd",
				"settlement_receivables_net_usd",
				"other_receivables_usd",
			}:
				entry["accounts_receivable_total_usd"] = _derive_accounts_receivable_total(entry)
			if field_path == "fcf_reported_fy2025_usd":
				entry["fcf_usd"] = value
			return


def _derive_override_metrics(
	truthpack: dict[str, Any],
	*,
	base_year: int | None,
) -> None:
	metricas = truthpack.setdefault("metricas_derivadas", {})
	for annual_entry in truthpack.get("historico_anual", []):
		if not isinstance(annual_entry, dict):
			continue
		total_ar = _derive_accounts_receivable_total(annual_entry)
		if total_ar is not None:
			annual_entry["accounts_receivable_total_usd"] = total_ar
			if base_year is not None and annual_entry.get("periodo") == f"FY{base_year}":
				truthpack["accounts_receivable_total_usd"] = total_ar

	pretax = _to_float(truthpack.get("pretax_income_usd"))
	ebit = _latest_annual_field(truthpack, "ebit_usd", base_year=base_year)
	if ebit is None:
		ebit = _to_float(truthpack.get("ebit_usd"))
	if pretax is None:
		pretax = _latest_annual_field(truthpack, "pretax_income_usd", base_year=base_year)

	bridge_components = [
		("interest_expense_net_usd", -1.0),
		("loss_on_sale_of_businesses_usd", -1.0),
		("gain_on_investments_net_usd", 1.0),
		("provision_credit_losses_investments_usd", -1.0),
		("other_loss_income_net_usd", -1.0),
	]
	if ebit is not None and pretax is not None:
		bridge_sum = ebit
		missing_component = False
		for field_name, sign in bridge_components:
			value = _to_float(truthpack.get(field_name))
			if value is None:
				value = _latest_annual_field(truthpack, field_name, base_year=base_year)
			if value is None:
				missing_component = True
				break
			bridge_sum += sign * value
		if not missing_component:
			truthpack["ebit_to_pretax_unexplained_usd"] = round(bridge_sum - pretax, 6)

	for field_name in (
		"trade_receivables_net_usd",
		"settlement_receivables_net_usd",
		"other_receivables_usd",
	):
		if truthpack.get(field_name) is None:
			truthpack[field_name] = _latest_annual_field(truthpack, field_name, base_year=base_year)

	fcf_reported = _to_float(truthpack.get("fcf_reported_fy2025_usd"))
	tds_fy = _to_float(truthpack.get("tds_wc_impact_fy2025_usd"))
	if fcf_reported is not None and tds_fy is not None and truthpack.get("fcf_adjusted_ex_tds_wc_fy2025_usd") is None:
		truthpack["fcf_adjusted_ex_tds_wc_fy2025_usd"] = fcf_reported - tds_fy
	q1 = _to_float(truthpack.get("tds_wc_impact_q1_2025_usd"))
	nine_m = _to_float(truthpack.get("tds_wc_impact_9m_2025_usd"))
	if tds_fy is not None and nine_m is not None:
		q4_impact = tds_fy - nine_m
		truthpack.setdefault("metricas_derivadas", {})["q4_2025_tds_wc_impact_implied_usd"] = q4_impact
		truthpack["q4_2025_tds_wc_impact_implied_usd"] = q4_impact

	if q1 is not None and truthpack.get("tds_wc_impact_h1_2025_usd") is not None and tds_fy is not None:
		metricas.setdefault("tds_working_capital_policy", {})
		metricas["tds_working_capital_policy"].update(
			{
				"reportado_y_ajustado_disponibles": truthpack.get("fcf_adjusted_ex_tds_wc_fy2025_usd") is not None,
				"normalizacion_principal": "fcf_ajustado_ex_tds_wc" if truthpack.get("fcf_adjusted_ex_tds_wc_fy2025_usd") is not None else "fcf_reportado",
				"q4_impact_positivo_implicito": truthpack.get("q4_2025_tds_wc_impact_implied_usd"),
			}
		)

	total_ar = _to_float(truthpack.get("accounts_receivable_total_usd"))
	trade_ar = _to_float(truthpack.get("trade_receivables_net_usd"))
	settlement_ar = _to_float(truthpack.get("settlement_receivables_net_usd"))
	if total_ar is not None and trade_ar is not None and settlement_ar is not None and total_ar > 0:
		settlement_mix_ratio = settlement_ar / total_ar
		receivables_guardrail = {
			"settlement_mix_ratio": round(settlement_mix_ratio, 6),
			"dso_collection_basis": "dso_trade",
			"dso_working_capital_basis": "dso_total",
			"collection_risk_signal": "trade_receivables_only",
			"working_capital_signal": "settlement_float_mix" if settlement_mix_ratio > 0.25 else "standard_receivables_mix",
		}
		metricas["receivables_guardrail"] = receivables_guardrail
		truthpack["receivables_guardrail"] = receivables_guardrail


def _derive_accounts_receivable_total(entry: dict[str, Any]) -> float | None:
	total = _to_float(entry.get("accounts_receivable_total_usd"))
	if total is not None:
		return total
	parts = [
		_to_float(entry.get("trade_receivables_net_usd")),
		_to_float(entry.get("settlement_receivables_net_usd")),
		_to_float(entry.get("other_receivables_usd")),
	]
	if all(part is not None for part in parts):
		return sum(part for part in parts if part is not None)
	legacy_total = _to_float(entry.get("accounts_receivable"))
	if legacy_total is not None:
		return legacy_total
	return None


def _latest_annual_field(
	truthpack: dict[str, Any],
	field_name: str,
	*,
	base_year: int | None,
) -> float | None:
	target_period = f"FY{base_year}" if base_year is not None else None
	for entry in reversed(truthpack.get("historico_anual", [])):
		if not isinstance(entry, dict):
			continue
		if target_period and entry.get("periodo") != target_period:
			continue
		value = _to_float(entry.get(field_name))
		if value is not None:
			return value
	if target_period is not None:
		for entry in reversed(truthpack.get("historico_anual", [])):
			if not isinstance(entry, dict):
				continue
			value = _to_float(entry.get(field_name))
			if value is not None:
				return value
	return None


def _apply_legacy_import_policy(
	truthpack: dict[str, Any],
	*,
	override_doc: dict[str, Any] | None,
	override_path: Path | None,
) -> None:
	dq = truthpack.setdefault("data_quality", {})
	warnings = dq.setdefault("warnings", [])
	limitaciones = dq.setdefault("limitaciones", [])
	confidence = _to_float(dq.get("confidence_score"))
	confidence_cap = 78.0 if override_doc is not None else 72.0
	if confidence is not None:
		dq["confidence_score"] = min(confidence, confidence_cap)

	review_required = sorted(_LEGACY_REVIEW_REQUIRED_FIELDS)
	review_note = (
		"LEGACY_IMPORT_POLICY: require filing-level review/override for unit-sensitive "
		"share/per-share fields and material bridge/receivables fields before relying on final verdicts."
	)
	if review_note not in warnings:
		warnings.append(review_note)
	if override_doc is None:
		missing_review = (
			"LEGACY_IMPORT_POLICY: no critical override file detected; treat unit-sensitive fields "
			"as pending filing-level review."
		)
		if missing_review not in warnings:
			warnings.append(missing_review)
	limit_note = (
		"Legacy-import policy active: unit-sensitive fields cannot be treated as non-material without explicit filing-level review."
	)
	if limit_note not in limitaciones:
		limitaciones.append(limit_note)

	suspicious_fields = _detect_suspicious_unit_family_fields(truthpack)
	if suspicious_fields and dq.get("overall_status") == "PASS":
		dq["status"] = "PARTIAL"
		dq["overall_status"] = "PARTIAL"
	if suspicious_fields:
		warnings.append(
			"LEGACY_IMPORT_POLICY: suspicious unit-family fields require explicit review: "
			+ ", ".join(sorted(suspicious_fields))
		)

	dq["legacy_import_policy"] = {
		"status": "ACTIVE",
		"review_required": True,
		"critical_fields_requiring_review": review_required,
		"override_file_applied": str(override_path) if override_doc is not None and override_path else None,
		"suspicious_unit_family_fields": sorted(suspicious_fields),
		"confidence_cap": confidence_cap,
	}


def _detect_suspicious_unit_family_fields(truthpack: dict[str, Any]) -> set[str]:
	suspicious: set[str] = set()
	share_like = {
		"shares_outstanding_end",
		"weighted_avg_basic",
		"weighted_avg_diluted",
		"acciones_diluidas",
	}
	per_share_like = {"eps_basic", "eps_diluted", "dividends_per_share"}
	for field_name in share_like:
		root_value = _to_float(truthpack.get(field_name))
		if root_value is not None and abs(root_value) >= 1_000_000_000:
			suspicious.add(field_name)
	for field_name in per_share_like:
		root_value = _to_float(truthpack.get(field_name))
		if root_value is not None and abs(root_value) >= 1_000:
			suspicious.add(field_name)
	for entry in [*truthpack.get("historico_anual", []), *truthpack.get("historico_trimestral", [])]:
		if not isinstance(entry, dict):
			continue
		for field_name in share_like:
			value = _to_float(entry.get(field_name))
			if value is not None and abs(value) >= 1_000_000_000:
				suspicious.add(field_name)
		for field_name in per_share_like:
			value = _to_float(entry.get(field_name))
			if value is not None and abs(value) >= 1_000:
				suspicious.add(field_name)
	return suspicious


def _resolve_market_data_payload(raw_market_data: Any, input_path: Path) -> dict[str, Any] | None:
	"""Resuelve market data priorizando el payload legacy y luego el sidecar del caso."""
	if isinstance(raw_market_data, dict):
		return raw_market_data

	sidecar_path = input_path.parent / "_market_data_output.json"
	if not sidecar_path.exists():
		return None

	try:
		loaded = json.loads(sidecar_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None

	return loaded if isinstance(loaded, dict) else None


def _build_period_entry(period_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
	fields = payload.get("fields", {})
	if not isinstance(fields, dict) or not fields:
		return None

	bucket = "annual" if _is_annual_period(period_name, payload) else "quarterly"
	entry: dict[str, Any] = {
		"periodo": period_name,
		"fecha_fin": payload.get("fecha_fin") or None,
		"tipo_periodo": payload.get("tipo_periodo") or None,
		"fuente_refs": {},
		"_bucket": bucket,
	}

	source_counter: Counter[str] = Counter()
	has_mapped_field = False

	for legacy_name, item in fields.items():
		if not isinstance(item, dict):
			continue
		canonical = _LEGACY_TO_CANONICAL.get(legacy_name)
		if canonical is not None:
			scaled = _scaled_field_value(legacy_name, item)
			entry[canonical] = scaled
			ref = _build_source_ref(item)
			if ref is not None:
				entry.setdefault("fuente_refs", {})[canonical] = ref
				if ref.get("source_id"):
					source_counter.update([str(ref["source_id"])])
			has_mapped_field = True
		elif legacy_name in {"accounts_receivable", "accounts_payable", "inventories"}:
			scaled = _scaled_field_value(legacy_name, item)
			entry[legacy_name] = scaled
			ref = _build_source_ref(item)
			if ref is not None:
				entry.setdefault("fuente_refs", {})[legacy_name] = ref
				if ref.get("source_id"):
					source_counter.update([str(ref["source_id"])])

	if not has_mapped_field:
		return None

	if source_counter:
		entry["source_filing"] = source_counter.most_common(1)[0][0]
	if _is_partial_period(period_name, payload):
		entry["_periodo_parcial"] = True
	if not entry.get("fuente_refs"):
		entry.pop("fuente_refs", None)
	return entry


def _extract_balance_snapshot(entry: dict[str, Any]) -> dict[str, Any] | None:
	snapshot = {
		"periodo": entry.get("periodo"),
		"fecha_fin": entry.get("fecha_fin"),
		"caja_usd": entry.get("caja_usd"),
		"activos_totales_usd": entry.get("activos_totales_usd"),
		"pasivos_totales_usd": entry.get("pasivos_totales_usd"),
		"patrimonio_usd": entry.get("patrimonio_usd"),
	}
	if not any(snapshot.get(field) is not None for field in _BALANCE_FIELDS):
		return None
	source_ref = entry.get("fuente_refs", {}) if isinstance(entry.get("fuente_refs"), dict) else {}
	snapshot["fuente_refs"] = {
		key: source_ref[key]
		for key in ("caja_usd", "activos_totales_usd", "pasivos_totales_usd", "patrimonio_usd")
		if key in source_ref
	}
	return snapshot


def _build_mercado_block(fecha: str, market_data: Any) -> dict[str, Any]:
	market: dict[str, Any] = {
		"fecha": fecha,
		"precio": {"valor": None, "divisa": "USD"},
		"acciones_diluidas": {"valor": None, "unidad": "acciones"},
		"market_cap_usd": None,
		"deuda_total_usd": None,
		"caja_y_equivalentes_usd": None,
		"deuda_neta_usd": None,
		"enterprise_value_usd": None,
		"traza_calculo_ev": {
			"formula": "EV = market_cap + deuda_total - caja",
			"inputs": {
				"market_cap_usd": None,
				"deuda_total_usd": None,
				"caja_y_equivalentes_usd": None,
			},
			"nota": "Importado desde truth_pack legacy.",
		},
	}
	normalized = _normalize_market_data(market_data)
	if normalized is None:
		return market

	price = normalized.get("price")
	shares = normalized.get("shares_outstanding")
	market_cap = normalized.get("market_cap_usd")
	debt = normalized.get("debt_total_usd")
	cash = normalized.get("cash_usd")
	ev = normalized.get("enterprise_value_usd")
	net_debt = normalized.get("net_debt_usd")

	market["precio"]["valor"] = _to_float(price)
	market["acciones_diluidas"]["valor"] = _to_float(shares)
	market["market_cap_usd"] = _to_float(market_cap)
	market["deuda_total_usd"] = _to_float(debt)
	market["caja_y_equivalentes_usd"] = _to_float(cash)
	market["deuda_neta_usd"] = _to_float(net_debt)
	market["enterprise_value_usd"] = _to_float(ev)
	market["traza_calculo_ev"]["inputs"] = {
		"market_cap_usd": market["market_cap_usd"],
		"deuda_total_usd": market["deuda_total_usd"],
		"caja_y_equivalentes_usd": market["caja_y_equivalentes_usd"],
	}
	return market


def _normalize_market_data(market_data: Any) -> dict[str, Any] | None:
	"""Normaliza snapshots de mercado flat/nested/SourcesPack a un formato común."""
	if not isinstance(market_data, dict):
		return None

	result = {
		"market_cap_usd": None,
		"shares_outstanding": None,
		"price": None,
		"debt_total_usd": None,
		"cash_usd": None,
		"enterprise_value_usd": None,
		"net_debt_usd": None,
	}

	for fuente in market_data.get("fuentes", []):
		if not isinstance(fuente, dict):
			continue
		datos = fuente.get("datos", {})
		if not isinstance(datos, dict):
			continue
		mcap_m = datos.get("market_cap_millones")
		if mcap_m is not None and result["market_cap_usd"] is None:
			mcap_value = _to_float(mcap_m)
			result["market_cap_usd"] = None if mcap_value is None else mcap_value * 1_000_000
		precio = datos.get("precio_cierre") or datos.get("precio")
		if precio is not None and result["price"] is None:
			result["price"] = _to_float(precio)
		shares_m = datos.get("shares_outstanding_millones")
		if shares_m is not None and result["shares_outstanding"] is None:
			shares_value = _to_float(shares_m)
			result["shares_outstanding"] = None if shares_value is None else shares_value * 1_000_000

	data = market_data.get("data", market_data)
	if not isinstance(data, dict):
		return result

	if result["market_cap_usd"] is None:
		result["market_cap_usd"] = _to_float(data.get("market_cap") or data.get("market_cap_usd"))
	if result["shares_outstanding"] is None:
		result["shares_outstanding"] = _to_float(
			data.get("shares_outstanding") or data.get("acciones_diluidas") or data.get("shs_outstand")
		)
	if result["price"] is None:
		result["price"] = _to_float(data.get("price") or data.get("precio"))
	result["debt_total_usd"] = _to_float(data.get("total_debt") or data.get("deuda_total_usd"))
	result["cash_usd"] = _to_float(
		data.get("cash") or data.get("cash_and_equivalents") or data.get("caja_y_equivalentes_usd")
	)
	result["enterprise_value_usd"] = _to_float(data.get("enterprise_value") or data.get("enterprise_value_usd"))
	result["net_debt_usd"] = _to_float(data.get("net_debt") or data.get("deuda_neta_usd"))
	return result


def _build_fuentes_usadas(
	payload: dict[str, Any],
	annual_entries: list[dict[str, Any]],
	quarterly_entries: list[dict[str, Any]],
) -> list[dict[str, str]]:
	ordered: list[dict[str, str]] = []
	seen: set[str] = set()

	for raw_name in (payload.get("sources") or {}).values():
		if isinstance(raw_name, str) and raw_name:
			source_id = _canonical_source_id(raw_name)
			if source_id and source_id not in seen:
				ordered.append({"source_id": source_id, "uso": "other"})
				seen.add(source_id)

	for entry in [*annual_entries, *quarterly_entries]:
		for ref in (entry.get("fuente_refs") or {}).values():
			if not isinstance(ref, dict):
				continue
			source_id = str(ref.get("source_id") or "").strip()
			if source_id and source_id not in seen:
				ordered.append({"source_id": source_id, "uso": "other"})
				seen.add(source_id)

	return ordered


def _build_fuente_refs_canonicos(
	annual_entries: list[dict[str, Any]],
	quarterly_entries: list[dict[str, Any]],
) -> dict[str, dict[str, str | None]]:
	refs: dict[str, dict[str, str | None]] = {}
	latest_refs: dict[str, dict[str, Any]] = {}
	for entry in [*annual_entries, *quarterly_entries]:
		fuente_refs = entry.get("fuente_refs")
		if not isinstance(fuente_refs, dict):
			continue
		for key, ref in fuente_refs.items():
			if isinstance(ref, dict):
				latest_refs[key] = ref

	mapping = {
		"cfo_usd": "cfo_usd",
		"ebit_usd": "ebit_usd",
		"accounts_receivable": "wc_change_accounts_receivable",
		"accounts_receivable_total_usd": "accounts_receivable_total_usd",
		"trade_receivables_net_usd": "trade_receivables_net_usd",
		"settlement_receivables_net_usd": "settlement_receivables_net_usd",
		"other_receivables_usd": "other_receivables_usd",
		"inventories": "wc_change_inventories",
		"accounts_payable": "wc_change_accounts_payable",
		"acciones_diluidas": "shares_outstanding_end",
		"weighted_avg_basic": "weighted_avg_basic",
		"weighted_avg_diluted": "weighted_avg_diluted",
		"pretax_income_usd": "pretax_income_usd",
		"interest_expense_net_usd": "interest_expense_net_usd",
		"loss_on_sale_of_businesses_usd": "loss_on_sale_of_businesses_usd",
		"gain_on_investments_net_usd": "gain_on_investments_net_usd",
		"provision_credit_losses_investments_usd": "provision_credit_losses_investments_usd",
		"other_loss_income_net_usd": "other_loss_income_net_usd",
		"capex_usd": "capex_cash_paid",
	}
	for source_key, target_key in mapping.items():
		if source_key in latest_refs:
			ref = latest_refs[source_key]
			refs[target_key] = {
				"source_id": ref.get("source_id"),
				"ubicacion": ref.get("ubicacion"),
				"cita_corta": ref.get("cita_corta"),
			}
	return refs


def _scaled_field_value(field_name: str, item: dict[str, Any]) -> float | None:
	value = _to_float(item.get("value"))
	if value is None:
		return None

	if field_name in _UNIT_FAMILY_RAW_FIELDS:
		return float(value)

	scale = str(item.get("scale") or "raw").strip().lower()
	multiplier = _SCALE_MULTIPLIERS.get(scale)

	if multiplier is None:
		multiplier = 1.0

	if multiplier == 1.0 and field_name in _RAW_THOUSANDS_HEURISTIC_FIELDS and abs(value) >= 1_000:
		multiplier = 1_000.0

	return float(value) * multiplier


def _build_source_ref(item: dict[str, Any]) -> dict[str, str | None] | None:
	source_id = _canonical_source_id(item.get("source_filing"))
	ubicacion = item.get("source_location")
	row_label = item.get("row_label")
	if not source_id and not ubicacion and not row_label:
		return None

	cita = None
	if isinstance(row_label, str) and row_label.strip():
		cita = row_label.strip()[:120]
	return {
		"source_id": source_id,
		"ubicacion": str(ubicacion) if ubicacion else None,
		"cita_corta": cita,
	}


def _canonical_source_id(raw: Any) -> str | None:
	if not isinstance(raw, str):
		return None
	text = raw.strip()
	if not text:
		return None
	name = Path(text).name
	stem = re.sub(r"\.(clean\.md|md|json|txt|htm|html|pdf)$", "", name, flags=re.IGNORECASE)
	return stem or None


def _periodo_base_from_legacy(payload: dict[str, Any]) -> str:
	derived = payload.get("derived_metrics", {})
	periodo_base = derived.get("periodo_base") if isinstance(derived, dict) else None
	if isinstance(periodo_base, str):
		low = periodo_base.lower()
		if "trimestre" in low or "suma_4_trimestres" in low:
			return "TTM"
		if low.startswith("fy"):
			return "FY"
	return "UNKNOWN"


def _legacy_ttm_fecha_fin(payload: dict[str, Any]) -> str | None:
	derived = payload.get("derived_metrics", {})
	if not isinstance(derived, dict):
		return None
	ttm = derived.get("ttm", {})
	if isinstance(ttm, dict):
		fecha = ttm.get("fecha_fin")
		return str(fecha) if fecha else None
	return None


def _merge_legacy_metric_fallbacks(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
	derived = payload.get("derived_metrics", {})
	if not isinstance(derived, dict):
		return result

	metricas = result.setdefault("metricas_derivadas", {})
	margins = derived.get("margins", {}) if isinstance(derived.get("margins"), dict) else {}
	multiples = derived.get("multiples", {}) if isinstance(derived.get("multiples"), dict) else {}
	returns = derived.get("returns", {}) if isinstance(derived.get("returns"), dict) else {}

	fallback_map = {
		"margen_bruto_pct": margins.get("gross_margin_pct"),
		"margen_operativo_pct": margins.get("operating_margin_pct"),
		"margen_fcf_pct": margins.get("fcf_margin_pct"),
		"fcf_yield_pct": multiples.get("fcf_yield_pct"),
		"ev_ebit": multiples.get("ev_ebit"),
		"ev_fcf": multiples.get("ev_fcf"),
		"interest_coverage": returns.get("interest_coverage"),
	}
	for key, val in fallback_map.items():
		if metricas.get(key) is None and val is not None:
			metricas[key] = val

	ttm = derived.get("ttm", {}) if isinstance(derived.get("ttm"), dict) else {}
	result_ttm = result.setdefault("ttm", {})
	if result_ttm.get("metodo") == "no_disponible" and ttm:
		result_ttm.update(
			{
				"periodo": "TTM",
				"fecha_fin": ttm.get("fecha_fin") or result_ttm.get("fecha_fin"),
				"ingresos_usd": _legacy_scaled_metric(ttm.get("ingresos")),
				"ebit_usd": _legacy_scaled_metric(ttm.get("ebit")),
				"cfo_usd": _legacy_scaled_metric(ttm.get("cfo")),
				"capex_usd": _legacy_scaled_metric(ttm.get("capex")),
				"fcf_usd": _legacy_scaled_metric(derived.get("fcf")),
				"metodo": ttm.get("metodo") or "legacy_import",
				"nota": ttm.get("nota") or "TTM recuperado desde truth_pack legacy.",
			}
		)

	return result


def _legacy_scaled_metric(value: Any) -> float | None:
	numeric = _to_float(value)
	if numeric is None:
		return None
	if abs(numeric) >= 1_000:
		return float(numeric) * 1_000.0
	return float(numeric)


def _quality_status_from_legacy(payload: dict[str, Any]) -> str | None:
	quality = payload.get("quality", {})
	if not isinstance(quality, dict):
		return None
	status = quality.get("validation_status")
	return str(status) if status else None


def _latest_field_value(
	quarterly_entries: list[dict[str, Any]],
	annual_entries: list[dict[str, Any]],
	field: str,
) -> float | None:
	for entries in (quarterly_entries, annual_entries):
		for entry in reversed(entries):
			value = _to_float(entry.get(field))
			if value is not None:
				scale = entry.get("tipo_periodo")
				if field in {"accounts_receivable", "accounts_payable", "inventories"} and scale == "anual":
					return value
				return value
	return None


def _sort_key(entry: dict[str, Any]) -> tuple[str, int, str]:
	fecha = str(entry.get("fecha_fin") or "")
	periodo = str(entry.get("periodo") or "")
	return (fecha, _period_rank(periodo), periodo)


def _period_rank(periodo: str) -> int:
	if re.match(r"^FY\d{4}$", periodo):
		return 50
	quarter_match = re.match(r"^Q([1-4])-(\d{4})$", periodo)
	if quarter_match:
		return int(quarter_match.group(1)) * 10
	if re.match(r"^H1-\d{4}$", periodo):
		return 25
	if re.match(r"^9M-\d{4}$", periodo):
		return 35
	return 0


def _is_annual_period(period_name: str, payload: dict[str, Any]) -> bool:
	tipo = str(payload.get("tipo_periodo") or "").lower()
	return period_name.startswith("FY") or tipo == "anual"


def _is_partial_period(period_name: str, payload: dict[str, Any]) -> bool:
	tipo = str(payload.get("tipo_periodo") or "").lower()
	return period_name.startswith("H1-") or period_name.startswith("9M-") or tipo in {"semestral", "unknown"}


def _bootstrap_case_state(
	*,
	case_dir: Path,
	ticker: str,
	date_str: str,
	artifact_name: str,
	source_path: Path,
	exchange: str,
	country: str,
	web_ir: str,
) -> None:
	init_or_load_state(
		case_dir,
		ticker,
		date_str,
		exchange=exchange,
		country=country,
		web_ir=web_ir,
	)
	now = datetime.now(timezone.utc).isoformat()

	def _modifier(state: dict[str, Any]) -> None:
		state.setdefault("pipeline", {}).setdefault(
			"SOURCES",
			{"estado": "PENDING", "artefacto": None, "artefacto_previo": None},
		)
		state["pipeline"]["SOURCES"] = {
			"estado": "DONE",
			"artefacto": source_path.name,
			"artefacto_previo": None,
			"model_profile": "legacy-import",
		}
		state.setdefault("pipeline", {}).setdefault(
			"TRUTH_PACK",
			{"estado": "PENDING", "artefacto": None, "artefacto_previo": None},
		)
		state["pipeline"]["TRUTH_PACK"] = {
			"estado": "DONE",
			"artefacto": artifact_name,
			"artefacto_previo": None,
			"model_profile": "legacy-import",
		}
		sub_steps = state.setdefault("sub_steps", {})
		for sub_step in SUB_STEPS.get("SOURCES", []):
			sub_steps[sub_step] = {
				"status": "DONE",
				"timestamp": now,
				"model": "legacy-import",
			}
		for sub_step in SUB_STEPS.get("TRUTH_PACK", []):
			sub_steps[sub_step] = {
				"status": "DONE",
				"timestamp": now,
				"model": "legacy-import",
			}
		state["estado_pipeline"] = "INCOMPLETO"
		state.setdefault("_meta", {})["ultima_actualizacion"] = now
		state["_meta"]["truthpack_import"] = {
			"source_file": str(source_path),
			"artifact": artifact_name,
			"imported_at_utc": now,
			"import_mode": "legacy_truth_pack",
		}
		if isinstance(state.get("notas"), str) and state["notas"].strip():
			state["notas"] += f"\nImported legacy TruthPack from {source_path.name}"
		else:
			state["notas"] = f"Imported legacy TruthPack from {source_path.name}"
		if "_errors" in state and "TRUTH_PACK" in state["_errors"]:
			del state["_errors"]["TRUTH_PACK"]
		if "_errors" in state and "SOURCES" in state["_errors"]:
			del state["_errors"]["SOURCES"]

	read_modify_write(case_dir, _modifier)


def _to_float(value: Any) -> float | None:
	if isinstance(value, (int, float)):
		return float(value)
	if isinstance(value, str):
		stripped = value.strip().replace(",", "")
		if not stripped:
			return None
		try:
			return float(stripped)
		except ValueError:
			return None
	return None
