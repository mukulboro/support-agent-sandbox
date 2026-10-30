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
- Setup instructions and a description of how to call the HTTP API directly (the supplied evaluation interface was not in the package).
- Tests for the router and ChatService (only the mock API and the tool dispatcher have unit tests).
- Escalate automatically after the last LLM retry fails.
- Known weak spots, see "Real failures still open" below.
- Optional: turn low-scoring audited conversations into draft golden cases.

---

# Evaluation

`evals/golden_set.json` is the frozen test set: 57 cases. 39 call an agent directly (docs answers, account questions,
multi-turn corrections, ambiguity, isolation and injected tool failures) and 18 go through the router and ChatService
(category `routing`). Facts come from `docs/PRODUCT_GUIDE.md` and `app/mock_api/data` (today is 2026-09-28). Cases are
not edited to make a run pass; new behaviour gets new cases.

```
uv run python -m evals.run --label <name>                          # run everything, traces in evals/runs/<name>/
uv run python -m evals.run --label <name> --only id1,id2            # a few cases
uv run python -m evals.run --label <name> --category routing --repeats 3   # repeat cases to see flaky ones
uv run python -m evals.compare <before> <after>                     # fixed, regressed and still failing, per case
uv run python -m evals.rescore --from <name> --to <name>-rescored   # score saved traces again, no LLM calls
```

Each turn is scored by code, with no LLM judge: required text (alternatives and regexes), forbidden text, sources,
tools that must be called and a tool-call cap. A case passes only if every turn passes. Each run also records latency,
LLM calls, tokens and an estimated cost (list prices, not billed amounts).

## Results so far (model: `gpt-5-nano`, reasoning `low`, `medium` on retry)

| Run | Pass | Notes |
|---|---|---|
| `baseline` | 26/39 (67%) | First run. 77 LLM calls, about $0.01, median latency 4.1s, p95 6.6s. |
| `baseline-rescored` | 34/39 (87%) | Same traces, scorer fixed (below). No new LLM calls. |
| `revised-priya` | 33/39 | Targeted change: do not add a status filter when looking up a named person. `acct-priya-payroll` fixed. The two new failures were a phrase my scorer missed and a badly designed exclusion, not behaviour changes. |
| `revised-no-offers` | 34/39 | Added a read-only rule (never offer actions the agent cannot do). The two earlier "regressions" passed again, which shows run-to-run noise; `acct-halberd-unpaid` failed (it sometimes skips the detail call, about 1 run in 3). |
| `routing-baseline` | 53/54 runs, 17/18 cases stable | 18 routed cases, 3 repeats each, router `gpt-5-mini`. The one failure was an over-strict check, not a routing error. About $0.034. |

By category after the scorer fix: account 10/11, multi_turn 5/5, isolation 1/1, tool_failure 4/4, out_of_scope 3/3,
docs 9/11, ambiguity 2/3, docs_gap 0/1.

### Scorer fix after the baseline

Reading the 13 baseline failures showed 8 were the scorer's fault. Every one of those answers was correct and honest.
The model writes curly apostrophes ("couldn’t") and the expected phrases used straight ones, which alone broke 6 cases.
Two phrase lists also missed equivalent wording ("not yet active or payable", "I hit an error getting the details").
`matches()` in `evals/run.py` now straightens quotes and the two lists got alternatives. Nothing was loosened to hide a
real failure.

### Real failures still open

| Case | What went wrong | Status |
|---|---|---|
| `acct-priya-payroll` | Filtered `status=ONBOARDED` for a named person, found nobody, never tried other statuses. Priya is DISMISSED. | FIXED in `revised-priya` |
| `acct-halberd-unpaid` | Sometimes answers from the bill list and never calls `get_vendor_invoice`, so the approver is not named. | CHANGE MADE (tool descriptions and a prompt rule), NOT YET RE-RUN |
| `acct-headcount-ambiguous` | Answered "21 employees" with no status split; the guide says headcount depends on status (16 active). | CHANGE MADE (`count_by_status` computed in code and a prompt rule), NOT YET RE-RUN |
| `docs-onboarding-tab` | Retrieval ranks the `The employee list` section 6th to 9th, so the answer cites the wrong sources. | IN PROGRESS: comparing 5 chunks and 3 sections against 12 and 6 |
| `docs-approve-bill` | Correctly says the docs have no approval steps, but never mentions the Needs approval tab. | PENDING |
| `docs-add-employee` | One-line answer with no wizard or steps. | PENDING |

The final results section (initial vs revised code, before and after on the same cases, regressions and the keep or
rollback decision) will replace this once the targeted change is done.

## Notes

- Docker builds are slow where PyPI is slow. Build with a nearer mirror that is fully synced:
  `PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple docker compose up --build`. A lagging mirror (Huawei was
  missing `hf-xet 1.8.0`) or a rate-limiting one (USTC returned 429 on parallel downloads) fails the install.
- The Qdrant server must match `qdrant-client` (both 1.20): the client leaves BM25 `Document` vectors for the server
  to compute, and an older server fails with "InferenceService is not initialized".
