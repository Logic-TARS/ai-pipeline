"""Job storage facade."""

from content_pipeline.job_store import STORE_VERSION, JobStore, utc_now

__all__ = ["STORE_VERSION", "JobStore", "utc_now"]
