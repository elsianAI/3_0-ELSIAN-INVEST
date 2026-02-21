#!/usr/bin/env python3
"""IR URL auto-resolver — shared utility for sec_fetcher and transcript_finder.

When the provided web_ir URL fails (404/timeout), automatically tries common
domain variants (subdomain swap, path alternatives) and validates with HEAD→GET.

Usage:
    from scripts.runners.ir_url_resolver import resolve_ir_base_url

    resolved = resolve_ir_base_url("https://www.somero.com/investors", session)
    # Returns "https://investors.somero.com" if original fails but variant works
"""

from __future__ import annotations

import sys
from typing import List, Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None  # type: ignore

HEADERS = {
    "User-Agent": "ELSIAN-INVEST-Bot/1.0 (research; bot@elsian-invest.local)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_VALID_STATUS = {200, 403, 429}
_WEAK_STATUS = {403, 429}


def _probe_url(session: requests.Session, url: str, timeout: int = 10) -> Optional[int]:
    """Try HEAD first (fast); fall back to GET. Return accepted status."""
    for method in (session.head, session.get):
        try:
            resp = method(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code in _VALID_STATUS:
                return int(resp.status_code)
            # If HEAD gives 405 (Method Not Allowed), try GET
            if method == session.head and resp.status_code == 405:
                continue
            return None
        except Exception:
            if method == session.head:
                continue
            return None
    return None


def build_ir_url_candidates(base_url: str) -> List[str]:
    """Generate URL variants to try when the original fails.

    For ``https://www.somero.com/investors`` generates:
      1. https://www.somero.com/investors          (original)
      2. https://investors.somero.com               (subdomain, no path)
      3. https://investors.somero.com/investors     (subdomain + path)
      4. https://www.somero.com/investor-relations   (alt path)
    """
    parsed = urlparse(base_url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or ""
    path = parsed.path.rstrip("/")

    candidates: list[str] = [base_url]

    # Determine base domain (strip www. if present)
    parts = netloc.split(".")
    if parts[0].lower() == "www":
        bare_domain = ".".join(parts[1:])
    else:
        bare_domain = netloc

    # Variant: investors.{bare_domain} + original path
    inv_sub = f"investors.{bare_domain}"
    if inv_sub != netloc:
        # Prefer root first; many IR sites are hosted here without /investors path.
        candidates.append(f"{scheme}://{inv_sub}")
        candidates.append(f"{scheme}://{inv_sub}{path}")

    # Variant: original domain + /investor-relations
    if "/investor-relations" not in path:
        candidates.append(f"{scheme}://{netloc}/investor-relations")

    # Variant: original domain + /investors
    if "/investors" not in path:
        candidates.append(f"{scheme}://{netloc}/investors")

    # Variant: bare domain (no www) + original path
    if bare_domain != netloc:
        candidates.append(f"{scheme}://{bare_domain}{path}")

    return list(dict.fromkeys(candidates))  # dedupe preserving order


def resolve_ir_base_url(
    web_ir: str,
    session: requests.Session,
    timeout: int = 10,
) -> Optional[str]:
    """Resolve an IR base URL, trying variants if the original fails.

    Returns the first URL that responds with 200/403/429, or *None* if
    all candidates fail.
    """
    if not web_ir or not web_ir.strip():
        return None

    base = web_ir.strip()
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    base = base.rstrip("/")

    candidates = build_ir_url_candidates(base)

    weak_match = None
    for url in candidates:
        status = _probe_url(session, url, timeout=timeout)
        if status is None:
            continue
        # Prefer hard success (200). Keep 403/429 only as weak fallback.
        if status == 200:
            if url != base:
                print(
                    f"[ir_url_resolver] Resolved: {web_ir} -> {url}",
                    file=sys.stderr,
                )
            return url
        if status in _WEAK_STATUS and weak_match is None:
            weak_match = url

    if weak_match:
        if weak_match != base:
            print(
                f"[ir_url_resolver] Resolved (weak): {web_ir} -> {weak_match}",
                file=sys.stderr,
            )
        return weak_match

    print(
        f"[ir_url_resolver] All {len(candidates)} candidates failed for {web_ir}",
        file=sys.stderr,
    )
    return None
