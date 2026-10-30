from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.agents import AuditorAgent, DynamicAgent, RouterAgent, StaticAgent, load_api_tools
from app.config import get_settings
from app.http.routes import router
from app.http.services import ChatService
from app.mock_api.mock_api import mock_request
from app.rag.ingestor import StaticKnowledgeIngester
from app.rag.retriever import Retriever
from app.repository.db import AuditStore
from app.repository.vector import VectorStore
from app.tools.convo_manager import ConversationManager
from app.tools.embed import Embedder
from app.tools.llm import LLM
from app.tools.logger import get_logger
from app.tools.tools import ToolDispatcher

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
    agents = {
        "static": StaticAgent(llm, retriever),
        "dynamic": DynamicAgent(
            llm, ToolDispatcher(mock_request, load_api_tools()), settings.today, settings.max_tool_rounds
        ),
    }
    router_llm = LLM(
        settings.openai_api_key,
        settings.router_model,
        settings.llm_retries,
        settings.router_reasoning_first,
        settings.router_reasoning_retry,
    )
    auditor_llm = LLM(
        settings.openai_api_key,
        settings.auditor_model,
        settings.llm_retries,
        settings.auditor_reasoning_first,
        settings.auditor_reasoning_retry,
    )
    audits = AuditStore(settings.db_path)
    app.state.audits = audits
    app.state.service = ChatService(
        RouterAgent(router_llm), agents, ConversationManager(), AuditorAgent(auditor_llm), audits
    )

    log.info("server ready")
    yield


app = FastAPI(title="Niural support agent", lifespan=lifespan)
app.include_router(router)
