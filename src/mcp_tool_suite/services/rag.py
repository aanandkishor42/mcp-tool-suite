"""Retrieval-augmented generation: index documents, retrieve, grounded answers."""

from __future__ import annotations

from dataclasses import dataclass

from mcp_tool_suite.config import Settings
from mcp_tool_suite.providers.base import ChatMessage, EmbeddingProvider, LLMProvider
from mcp_tool_suite.services.documents import chunk_text, load_text
from mcp_tool_suite.services.vectorstore import Hit, InMemoryVectorStore

_ANSWER_SYSTEM = (
    "You are a precise retrieval assistant. Answer ONLY from the provided context. "
    "If the context does not contain the answer, say you don't know. "
    "Cite the sources you used inline as [1], [2], ... matching the numbered context."
)


@dataclass(slots=True)
class Citation:
    index: int
    source: str
    score: float
    snippet: str

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "source": self.source,
            "score": round(self.score, 4),
            "snippet": self.snippet,
        }


class RagService:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        store: InMemoryVectorStore,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.embedder = embedder
        self.store = store

    async def index(self, collection: str, source: str) -> dict[str, object]:
        """Load *source*, chunk it, embed the chunks and persist them."""
        text = await load_text(source, timeout=self.settings.request_timeout)
        chunks = chunk_text(
            text, size=self.settings.chunk_size, overlap=self.settings.chunk_overlap
        )
        if not chunks:
            return {"collection": collection, "source": source, "chunks": 0, "characters": 0}

        vectors = await self.embedder.embed(chunks)
        ids = [f"{collection}-{i}" for i in range(self.store.count(collection), self.store.count(collection) + len(chunks))]
        metadatas = [{"source": source, "chunk_index": i} for i in range(len(chunks))]
        self.store.add(
            collection, ids=ids, vectors=vectors, texts=chunks, metadatas=metadatas
        )
        return {
            "collection": collection,
            "source": source,
            "chunks": len(chunks),
            "characters": len(text),
        }

    async def search(
        self, collection: str, query: str, *, top_k: int | None = None
    ) -> list[Hit]:
        [query_vector] = await self.embedder.embed([query])
        return self.store.search(
            collection, query_vector, top_k=top_k or self.settings.default_top_k
        )

    async def answer(
        self, collection: str, question: str, *, top_k: int | None = None
    ) -> dict[str, object]:
        hits = await self.search(collection, question, top_k=top_k)
        if not hits:
            return {
                "answer": "No documents are indexed in this collection yet. "
                "Call `index_document` first.",
                "citations": [],
            }

        context = "\n\n".join(
            f"[{i}] (source: {hit.metadata.get('source', 'unknown')})\n{hit.text}"
            for i, hit in enumerate(hits, start=1)
        )
        if self.embedder.name == "hashing":
            provider_note = (
                " NOTE: retrieval uses offline 'hashing' embeddings, so chunk ranking "
                "is keyword-based rather than semantic. Set EMBED_PROVIDER=ollama or "
                "openai for true semantic search."
            )
        else:
            provider_note = ""

        messages = [
            ChatMessage("system", _ANSWER_SYSTEM + provider_note),
            ChatMessage("user", f"Context:\n{context}\n\nQuestion: {question}"),
        ]
        answer = await self.llm.complete(messages)
        citations = [
            Citation(
                index=i,
                source=str(hit.metadata.get("source", "unknown")),
                score=hit.score,
                snippet=hit.text[:200],
            )
            for i, hit in enumerate(hits, start=1)
        ]
        return {"answer": answer, "citations": [c.as_dict() for c in citations]}
