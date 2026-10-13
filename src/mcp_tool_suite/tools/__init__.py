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
    "task_augmentable_tools",
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


def task_augmentable_tools() -> list[str]:
    """Names of bundled tools that may run as background MCP Tasks (2025-11-25)."""
    return [
        plugin.name
        for plugin in default_plugins()
        if getattr(plugin, "task_support", None) in ("optional", "required")
    ]
