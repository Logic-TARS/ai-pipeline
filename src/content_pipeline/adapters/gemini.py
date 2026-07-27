"""Gemini adapter facade.

New code should import Gemini integration through this module.  The legacy
``content_pipeline.tools.gemini_client`` module remains as a compatibility
implementation detail.
"""

from content_pipeline.tools.gemini_client import call_gemini_skill
from content_pipeline.tools.gemini_mcp_client import GeminiMcpClient, call_gemini_mcp

__all__ = ["GeminiMcpClient", "call_gemini_mcp", "call_gemini_skill"]
