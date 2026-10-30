from app.rag.ingestor import StaticKnowledgeIngester
from app.repository.vector import VectorStore
from app.tools.embed import Embedder


class Retriever:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        ingester: StaticKnowledgeIngester,
        chunks_to_fetch: int = 5,
        sections_to_return: int = 3,
        max_section_chars: int = 3000,
    ):
        self.embedder = embedder
        self.store = store
        self.ingester = ingester  # holds the heading path -> full section map
        self.chunks_to_fetch = chunks_to_fetch
        self.sections_to_return = sections_to_return
        self.max_section_chars = max_section_chars

    def retrieve(self, query: str) -> list[dict]:
        """Returns up to 3 unique sections as [{title, section, score}], best first. title is the citation."""
        query_vector = self.embedder.embed([query])[0]
        hits = self.store.search(query_vector, query, self.chunks_to_fetch)

        results = []
        seen = set()
        for hit in hits:
            if hit["title"] in seen:  # several chunks of one section should not repeat it
                continue
            seen.add(hit["title"])
            section = self.ingester.sections.get(hit["title"], hit["text"])
            results.append({"title": hit["title"], "section": section[: self.max_section_chars], "score": hit["score"]})
        return results[: self.sections_to_return]