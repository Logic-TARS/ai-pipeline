"""MoneyPrinterTurbo adapter facade."""

from content_pipeline.tools.finance_mpt_client import FinanceMptResult, call_finance_mpt
from content_pipeline.tools.mpt_client import call_mpt
from content_pipeline.tools.narrated_mpt_client import NarratedMptResult, call_narrated_mpt

__all__ = [
    "FinanceMptResult",
    "NarratedMptResult",
    "call_finance_mpt",
    "call_mpt",
    "call_narrated_mpt",
]
