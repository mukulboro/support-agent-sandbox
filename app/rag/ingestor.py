import re
import uuid
from pathlib import Path

from chonkie import Chunk, Pipeline

from app.repository.vector import VectorStore
from app.tools.embed import Embedder
from app.tools.logger import get_logger

log = get_logger(__name__)


class StaticKnowledgeIngester:
    """Turns the product guide into chunks in the vector store. Safe to call ingest() on every startup."""

    def __init__(self, guide_path: Path, embedder: Embedder, store: VectorStore, chunk_size: int = 300):
        self.guide_path = guide_path
        self.embedder = embedder
        self.store = store
        self.chunk_size = chunk_size
        self.sections: dict[str, str] = {}  # heading path -> full section text, used later to give the LLM more context

    def ingest(self) -> None:
        doc = (
            Pipeline()
            .fetch_from("file", path=str(self.guide_path))
            .process_with("markdown")
            .chunk_with("recursive", chunk_size=self.chunk_size)
            .run()
        )

        headings = self.find_headings(doc.content)
        self.sections = self.build_sections(doc.content, headings)

        # Each chunk's id is a hash of its content, so unchanged chunks keep the same id
        wanted: dict[str, dict[str, str]] = {}
        for chunk in doc.chunks:
            point = {"title": self.title_for(chunk, headings), "text": chunk.text.strip()}
            wanted[self.make_id(point)] = point

        existing = self.store.existing_ids()
        new_ids = [i for i in wanted if i not in existing]
        stale_ids = [i for i in existing if i not in wanted]

        if new_ids:
            vectors = self.embedder.embed([f"{wanted[i]['title']}\n{wanted[i]['text']}" for i in new_ids])
            self.store.upsert([{"id": i, "vector": v, **wanted[i]} for i, v in zip(new_ids, vectors)])
        if stale_ids:
            self.store.delete(stale_ids)

        log.info(
            "ingest done: %d sections, %d chunks, %d added, %d deleted, %d unchanged",
            len(self.sections), len(wanted), len(new_ids), len(stale_ids), len(wanted) - len(new_ids),
        )

    def find_headings(self, text: str) -> list[tuple[int, str]]:
        """Returns [(offset in text, heading path)], e.g. (1204, 'Part 2 — Niural Pay > Bills')."""
        headings: list[tuple[int, str]] = []
        path: list[tuple[int, str]] = []  # (level, title)
        offset = 0
        for line in text.splitlines(keepends=True):
            match = re.match(r"^(#{1,6})\s+(.*)", line)
            if match:
                level = len(match.group(1))
                while path and path[-1][0] >= level:  # drop siblings and deeper headings
                    path.pop()
                path.append((level, match.group(2).strip()))
                headings.append((offset, " > ".join(title for _, title in path)))
            offset += len(line)
        return headings

    def build_sections(self, text: str, headings: list[tuple[int, str]]) -> dict[str, str]:
        sections: dict[str, str] = {}
        for i, (start, title) in enumerate(headings):
            end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
            sections[title] = text[start:end].strip()
        return sections

    def title_for(self, chunk: Chunk, headings: list[tuple[int, str]]) -> str:
        """The chunk's heading is the last heading that starts at or before the chunk."""
        title = ""
        for offset, heading in headings:
            if offset > chunk.start_index:
                break
            title = heading
        return title

    def make_id(self, point: dict[str, str]) -> str:
        # model name is in the key so switching embedding models re-embeds everything
        key = f"{self.embedder.model}|{point['title']}|{point['text']}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))