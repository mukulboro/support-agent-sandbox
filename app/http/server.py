from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.agents import RouterAgent, StaticAgent
from app.config import get_settings
from app.http.routes import router
from app.http.services import ChatService
from app.rag.ingestor import StaticKnowledgeIngester
from app.rag.retriever import Retriever
from app.repository.vector import VectorStore
from app.tools.convo_manager import ConversationManager
from app.tools.embed import Embedder
from app.tools.llm import LLM
from app.tools.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: build everything and ingest the guide. The server only accepts requests once this is done."""
    settings = get_settings()

    embedder = Embedder(settings.openai_api_key, settings.embed_model)
    store = VectorStore(settings.qdrant_url, settings.collection, settings.embed_dimension)
    ingester = StaticKnowledgeIngester(settings.guide_path, embedder, store, settings.chunk_size)
    ingester.ingest()

    retriever = Retriever(
        embedder, store, ingester, settings.chunks_to_fetch, settings.sections_to_return, settings.max_section_chars
    )
    llm = LLM(
        settings.openai_api_key,
        settings.llm_model,
        settings.llm_retries,
        settings.llm_reasoning_first,
        settings.llm_reasoning_retry,
    )
    app.state.store = store  # the health check asks it whether Qdrant is ready
    app.state.service = ChatService(RouterAgent(), StaticAgent(llm, retriever), ConversationManager())

    log.info("server ready")
    yield


app = FastAPI(title="Niural support agent", lifespan=lifespan)
app.include_router(router)
