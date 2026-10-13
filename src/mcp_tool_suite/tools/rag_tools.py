"""RAG tools: index a document, search it, and answer questions with citations."""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.registry import ToolCallable


class IndexDocumentTool:
    name = "index_document"
    description = (
        "Load a document and prepare it for question answering. The source may be "
        "an http(s) URL, a local file path (PDF or text), or raw text pasted directly. "
        "Content is chunked, embedded and stored in a named collection. Call this "
        "before document_qa or semantic_search on new content."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def index_document(source: str, collection: str = "default") -> dict:
            """Index a document into a collection."""
            return await ctx.rag.index(collection, source)

        return index_document


class DocumentQaTool:
    name = "document_qa"
    description = (
        "Answer a question grounded in previously indexed documents, returning the "
        "answer plus numbered citations. Use after index_document. Include the "
        "collection name if you indexed into a non-default one."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def document_qa(
            question: str, collection: str = "default", top_k: int = 4
        ) -> dict:
            """Answer a question from indexed documents with citations."""
            return await ctx.rag.answer(collection, question, top_k=top_k)

        return document_qa


class SemanticSearchTool:
    name = "semantic_search"
    description = (
        "Return the most relevant chunks from an indexed collection for a query, "
        "each with a relevance score and source. Use for raw retrieval when you want "
        "the passages themselves rather than a synthesized answer."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def semantic_search(
            query: str, collection: str = "default", top_k: int = 4
        ) -> list[dict]:
            """Return the top matching chunks for a query."""
            hits = await ctx.rag.search(collection, query, top_k=top_k)
            return [
                {
                    "id": hit.id,
                    "score": round(hit.score, 4),
                    "source": str(hit.metadata.get("source", "unknown")),
                    "text": hit.text,
                }
                for hit in hits
            ]

        return semantic_search
