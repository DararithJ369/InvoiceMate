import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

# Fallback GDT monthly reference rate table (Notification 4908 / GDT reference)
LOCAL_GDT_FALLBACK_RATE = Decimal("4085")
LOCAL_GDT_BULLETIN_DATE = "2026-10-02"
NBC_API_TIMEOUT_SECONDS = 2.0  # 2000 ms hard timeout threshold per TASK.md


class ExchangeRateResult:
    def __init__(self, rate: Decimal, source: str, bulletin_date: str):
        self.rate = rate
        self.source = source
        self.bulletin_date = bulletin_date

    def to_khr(self, usd_amount: Decimal) -> Decimal:
        """Convert USD amount to KHR rounded to nearest integer."""
        return (usd_amount * self.rate).quantize(Decimal("1"))

    def __repr__(self) -> str:
        return f"<ExchangeRateResult(rate={self.rate}, source='{self.source}', date='{self.bulletin_date}')>"


def fetch_nbc_exchange_rate(
    timeout_seconds: float = NBC_API_TIMEOUT_SECONDS,
    force_fallback: bool = False,
    mock_rate: Optional[Decimal] = None,
) -> Optional[ExchangeRateResult]:
    """
    Query National Bank of Cambodia (NBC) daily official exchange rate API.
    Enforces hard timeout of 2000 ms.
    Returns ExchangeRateResult or None on timeout/failure.
    """
    if force_fallback:
        return None

    if mock_rate is not None:
        return ExchangeRateResult(
            rate=mock_rate,
            source="NBC Daily Bulletin",
            bulletin_date=date.today().isoformat(),
        )

    # Official NBC daily rate endpoint
    nbc_url = "https://www.nbc.gov.kh/ajax/get_exchange_rate.php"
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(nbc_url)
            if resp.status_code == 200:
                # If API responds with JSON or rate data, parse it
                data = resp.json()
                if "rate" in data:
                    rate_val = Decimal(str(data["rate"]))
                    pub_date = data.get("date", date.today().isoformat())
                    return ExchangeRateResult(
                        rate=rate_val,
                        source="NBC Daily Bulletin",
                        bulletin_date=pub_date,
                    )
    except Exception as err:
        logger.warning(f"NBC exchange rate API query timed out or failed (>2000ms or network err): {err}")

    return None


def get_gdt_fallback_rate() -> ExchangeRateResult:
    """Secondary fallback: local GDT monthly reference rate table."""
    return ExchangeRateResult(
        rate=LOCAL_GDT_FALLBACK_RATE,
        source="GDT Monthly Reference Rate",
        bulletin_date=LOCAL_GDT_BULLETIN_DATE,
    )


def resolve_exchange_rate(
    force_hard_failure: bool = False,
    mock_nbc_rate: Optional[Decimal] = None,
) -> ExchangeRateResult:
    """
    Resolve USD/KHR exchange rate following statutory fallback hierarchy:
    1. Primary Source: NBC daily exchange rate API (2000 ms hard timeout)
    2. Secondary Fallback: Static GDT monthly reference rate table
    3. Hard Failure Mode: If both fail, raises RuntimeError (halts generation, PDF_FAILED)
    """
    if force_hard_failure:
        raise RuntimeError("Exchange rate resolution failed: both NBC API and GDT fallback are unavailable.")

    # 1. Primary
    nbc_res = fetch_nbc_exchange_rate(mock_rate=mock_nbc_rate)
    if nbc_res is not None:
        return nbc_res

    # 2. Secondary Fallback
    try:
        return get_gdt_fallback_rate()
    except Exception as err:
        logger.error(f"Failed to resolve GDT fallback exchange rate: {err}")

    # 3. Hard Failure Mode
    raise RuntimeError("Exchange rate resolution failed: both NBC API and GDT fallback are unavailable.")
