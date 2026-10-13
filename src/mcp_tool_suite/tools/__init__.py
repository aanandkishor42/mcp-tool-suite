"""Tool plugins. Import ``default_plugins`` for the bundled set."""

from __future__ import annotations

from mcp_tool_suite.registry import ToolPlugin
from mcp_tool_suite.tools.analyze import AnalyzeDocumentTool
from mcp_tool_suite.tools.code_review import ReviewCodeTool
from mcp_tool_suite.tools.dashboard import UsageStatsTool
from mcp_tool_suite.tools.data_analysis import AnalyzeDataTool
from mcp_tool_suite.tools.email import EmailAssistantTool
from mcp_tool_suite.tools.rag_tools import (
    DocumentQaTool,
    IndexDocumentTool,
    SemanticSearchTool,
)
from mcp_tool_suite.tools.report import GenerateReportTool
from mcp_tool_suite.tools.web_research import WebResearchTool

__all__ = [
    "AnalyzeDocumentTool",
    "AnalyzeDataTool",
    "DocumentQaTool",
    "EmailAssistantTool",
    "GenerateReportTool",
    "IndexDocumentTool",
    "ReviewCodeTool",
    "SemanticSearchTool",
    "UsageStatsTool",
    "WebResearchTool",
    "default_plugins",
]


def default_plugins() -> list[ToolPlugin]:
    """The bundled tool set. Add your own plugin here to expose it."""
    return [
        # Document / RAG
        IndexDocumentTool(),
        SemanticSearchTool(),
        DocumentQaTool(),
        AnalyzeDocumentTool(),
        # Engineering / data / web / reporting
        ReviewCodeTool(),
        AnalyzeDataTool(),
        WebResearchTool(),
        GenerateReportTool(),
        # Communication
        EmailAssistantTool(),
        # Observability
        UsageStatsTool(),
    ]
