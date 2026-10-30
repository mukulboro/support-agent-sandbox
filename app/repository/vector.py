from qdrant_client import QdrantClient, models


class VectorStore:
    """Qdrant collection holding each chunk twice: a dense (embedding) vector and a BM25 sparse vector."""

    def __init__(self, url: str, collection: str, dimension: int = 1536):
        self.client = QdrantClient(url=url) if url else QdrantClient(":memory:")
        self.collection = collection

        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection,
                vectors_config={"dense": models.VectorParams(size=dimension, distance=models.Distance.COSINE)},
                sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )

    def existing_ids(self) -> set[str]:
        ids = set()
        offset = None
        while True:
            points, offset = self.client.scroll(self.collection, offset=offset, limit=256, with_payload=False)
            ids.update(str(p.id) for p in points)
            if offset is None:
                return ids

    def upsert(self, points: list[dict]):
        """Each point is {id, vector, title, text}."""
        self.client.upsert(self.collection, [
            models.PointStruct(
                id=p["id"],
                vector={
                    "dense": p["vector"],
                    "bm25": models.Document(text=f"{p['title']}\n{p['text']}", model="Qdrant/bm25"),
                },
                payload={"title": p["title"], "text": p["text"]},
            )
            for p in points
        ])

    def search(self, query_vector: list[float], query_text: str, limit: int = 4) -> list[dict]:
        """Hybrid search: dense and BM25 each pick 20 candidates, then Qdrant merges them with RRF."""
        result = self.client.query_points(
            self.collection,
            prefetch=[
                models.Prefetch(query=query_vector, using="dense", limit=20),
                models.Prefetch(query=models.Document(text=query_text, model="Qdrant/bm25"), using="bm25", limit=20),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [{"title": p.payload["title"], "text": p.payload["text"], "score": p.score} for p in result.points]

    def delete(self, ids: list[str]):
        self.client.delete(self.collection, models.PointIdsList(points=ids))