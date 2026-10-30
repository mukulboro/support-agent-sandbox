> **This is only a placeholder README.** It is my own design notes, jotted down while planning, with a status marker
> on each idea. The real documentation (what it does, setup, API, evaluation and results) is in
> [`.github/README.md`](.github/README.md), which GitHub shows on the repository page.

# Support Agent Sandbox: design notes

Customer service agent
1. can answer from supplied documentation (static queries)
2. can answer from API (dynamic queries)

- IMPLEMENTED: Routing Agent gets query first, it can rewrite if needed
- IMPLEMENTED (at most one query per agent): If there is mixed queries, router can split queries to both agents or one agent
multiple times and then combine the context
- IMPLEMENTED: route each query per call for this demo
- IMPLEMENTED: decides dyanmic or static, moves query to dynamic/static agent with proper convo history
- IMPLEMENTED (router actions: answer, unsupported, escalate, end): It can also decide that the query is beyond its current capabilities and decide to end convo or escalate
- IMPLEMENTED (it does use one tool call, answer_question, to return the answer and the sources it used): static agent does not need any tool calls; we can directly embed retrieved query in context 
and ask it to answer
- IMPLEMENTED (6 tools in api_tools.yaml, run by ToolDispatcher): dynamic agent needs tool calls to get the proper API call

For Static Agent

1. Data ingestion
- IMPLEMENTED: Read the source md file
- IMPLEMENTED (via chonkie Pipeline, process_with("markdown")): Chonkie MDChef, parse content
- IMPLEMENTED: Run recursive chunker on parsed content. Example:
```python
from chonkie import RecursiveChunker
from chonkie.chef import MarkdownChef

# Read Markdown file
with open("knowledge_base.md", "r", encoding="utf-8") as f:
    markdown_content = f.read()

# Parse Markdown into structured content
chef = MarkdownChef()
parsed_content = chef.prepare(markdown_content)

# Initialize recursive chunker
chunker = RecursiveChunker(
    chunk_size=512,
    min_characters_per_chunk=24,
)

# Create chunks
chunks = chunker.chunk(parsed_content)

# Inspect chunks
for i, chunk in enumerate(chunks):
    print(f"\n--- Chunk {i + 1} ---")
    print(chunk.text)
    print(f"Token count: {chunk.token_count}")
```
- IMPLEMENTED: Generate idempotency keys for eahc chunk, decide if updates or additions are needed
- IMPLEMENTED: if needed, vectorize with openAI and update/add to qdrant vector DB
- IMPLEMENTED: in the payload, add relevant things (like citation string), i was thinking, if a certain chunk gets matched 
sematically, i'd want to inject the entire md heading for more context. I was thinking
in the payload we store the md heading title and always store each MD section in memory
in a simple hashmap

- IMPLEMENTED: This happens at server start uo with proper logging

Whenver a query comes,
- IMPLEMENTED: Router agent decides on the static agent, RAG happens automatically, 
context + history injected into the static agent continues
- IMPLEMENTED: The reference is in the traces, convo context manager formats it properly

Convo history handling
- IMPLEMENTED: have a begin convo route in the server, returns the convo ID
- IMPLEMENTED (main.py chat is the client, and also shows route, tool calls and sources): client uses that convo ID to make subsequent chat calls
- IMPLEMENTED: message history handled server side so internal messages and all are not exposed to
client
- IMPLEMENTED: history removed from memory, after convo ends or is escalated. not storing for demo

Dynamic Agent
- IMPLEMENTED: After router decides on the dynamic agent, it gets the query, chooses appropriate tool
call
- IMPLEMENTED: gets convo history and shit

If any tool call fails:
1. IMPLEMENTED (covered by the tool_failure eval cases): case 1: if the mock api returns no data, tell that i dont have access to this
resource right now, do you want to ask anything else, escalate or end
2. PARTIAL (retries with higher reasoning and the apology are done; escalating after the last retry is not, the conversation stays open): case 2: if LLM fails, apologize and retry for N times (default 3), then escalate

IMPLEMENTED: Each LLM response comes with the tool calls and decision traces. The convo context
manager decides what to hold internally, want to expose to client

IMPLEMENTED (runs in the background when a convo ends, however it ends; stored in SQLite; GET /audits and main.py audit
let a human approve or reject its suggestions, nothing is applied automatically): After a convo ends, we send this context to an audiotor agent, it scores the convo
with reasons, suggest points to improve, and store in db. This is the "self improving"
aspect of the system. Human in the loop for changes

## Status

COMPLETED: static agent (hybrid retrieval, sources), dynamic agent (6 tools, counts and totals computed in code), router,
conversation manager, HTTP server with health checks, chat CLI, auditor with a human review mode, Docker stack, golden set
with eval runner, and the evaluation runs below.

PENDING:
- Tests for the router and ChatService (only the mock API and the tool dispatcher have unit tests).
- Escalate automatically after the last LLM retry fails.
- Two answers are still weak: `docs-pending-onboarding` (says it cannot find a definition) and `acct-failed-payment-no-id`
  (asks for the invoice when only the transaction id can explain a failed payment).
- Optional: turn low-scoring audited conversations into draft golden cases.

Setup, the HTTP API, the evaluation and its results are documented in [`.github/README.md`](.github/README.md).
