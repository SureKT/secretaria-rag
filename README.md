# SecretarIA — a self-hosted RAG assistant for school administration

> **Public release of a delivered project.** The engineering is here in full: ingestion,
> retrieval, the agent workflows, the evaluation suite and the decision log. What is *not*
> here is the schools' own content — the knowledge base under `data/` has been replaced
> with a small fictional corpus of the same shape, so the pipeline still runs and the
> chunking strategy is still legible. Internal addresses and identifiers are likewise
> placeholders.
>
> The most useful part is probably [`docs/historial-decisiones.md`](docs/historial-decisiones.md):
> the problems, in the order I hit them, with their causes.

*The name is a pun that does not survive translation: **secretaría** is the school office,
and **IA** is Spanish for AI.*

A conversational assistant for the administration office of two public vocational schools in
Valencia, answering questions about course offerings, admissions, grants, timetables and
administrative procedures. It runs entirely on the institute's own hardware — an NVIDIA
DGX Spark — so no student or staff query leaves the building.

I designed, built and delivered it end to end: scoping with the centres, ingestion,
retrieval, the agent, the evaluation suite and deployment.

---

## Architecture

```
User → Typebot (chat UI, HTTPS via nginx)
          │
          ▼
     n8n AI Agent ──── session memory (per sessionId)
          │
          ├── tool: "Consultas"
          │        │
          │        ├─ embed query   → mxbai-embed-large (1024-dim)
          │        └─ vector search → Qdrant, cosine, top-6 chunks
          │
          └── LLM → Ollama (mistral-small3.2:24b) → answer
```

Knowledge base: structured Markdown and YAML, ingested by a script into Qdrant.
Everything self-hosted: Ollama, Qdrant, PostgreSQL, Typebot and nginx under Docker
Compose, with inference on the institute's GPU.

---

## Four decisions worth explaining

### 1. I chose n8n. Then I replaced it with FastAPI.

The first version orchestrated everything in n8n, and it worked — it was in front of real
users. But n8n could only return a *completed* response, so every answer arrived as a wall
of text after several seconds of silence, and people read that pause as the bot being
broken. Nothing about the model or the prompt fixes a problem that lives in the delivery
layer.

So I rewrote the backend in FastAPI to stream tokens. The interaction became incremental
instead of a blocking wait, with the same model and the same answers.

The point isn't that FastAPI beats n8n. It's that the tool I had picked myself turned out
to have a ceiling I only discovered by shipping, and the cheapest moment to admit that was
immediately.

### 2. Full-text search was silently returning the wrong documents

Questions about *Óptica* kept coming back with content about *Enfermería*.

The obvious suspect is the model. It wasn't. Qdrant's full-text search performs no
accent-folding, so the query `Óptica` never matched the stored `optica`, and the retriever
handed the model a context that simply did not contain the answer. The model was doing its
best with the wrong documents.

I moved retrieval to cosine similarity over embeddings, where meaning survives the accent.

The lesson I actually took from it: in a RAG system, a wrong answer has at least two
possible causes, and they need different fixes. Which led to the next decision.

### 3. A retrieval audit is a separate tool from the chatbot

`audit_retrieval.sh` takes a query and prints the chunks the vector DB returns, **with
their similarity scores**, and nothing else. No agent, no LLM.

A second script runs the pipeline end to end without the orchestrator — embed, search,
generate — and reports the answer with its latency.

Together they answer the only question that matters when output is bad: *is retrieval
returning the right context, and is the model failing to use it?* Guessing at that is
expensive; two small scripts make it a five-second check.

### 4. Chunking is hierarchical, not a fixed splitter

Naive fixed-size splitting broke this corpus in two specific ways:

- A chunk containing only a heading, or a fragment of a list, would rank above the chunk
  holding the actual content — the retriever preferred a stub because it looked topically
  pure.
- A chunk lifted out of the middle of a document lost the headings that gave it meaning.
  "First year: ..." is useless when the embedding doesn't know which course it belongs to.

So ingestion prepends the parent headings to each chunk before embedding, and keeps
logical units — a course's full module list — whole rather than splitting them at an
arbitrary character count. Base size is 500 characters with 100 of overlap, but the
structure of the document wins over the number.

---

## Evaluation

Model choice was made from a benchmark suite, not from impressions.

36 tests across categories covering each professional family, timetables and
administrative procedures, plus two kinds that matter more than the happy path:

- **Negative cases** — questions outside the assistant's scope, where the correct
  behaviour is to decline and redirect rather than to improvise.
- **Multi-turn chains** — tests that share a session ID, so a later question depends on
  an earlier answer. This is what verifies conversational memory rather than assuming it.

Each test records pass/fail and latency. Running the suite across candidate models is how
`mistral-small3.2:24b` was chosen over the alternatives tested.

The suite also caught false positives in its own assertions — a keyword check passing for
the wrong reason — which I fixed. An eval you don't audit is a comfort blanket.

---

## What it does not do

Being explicit about the edges:

- **No reranking.** Retrieval is top-k by cosine similarity and stops there. A cross-encoder
  reranking pass is the obvious next improvement.
- **Assertions are keyword-based**, not model-graded. Cheap, deterministic and fast, but
  they check for the presence of the right facts rather than the quality of the answer.
- **No online evaluation.** Everything is offline; there is no feedback signal from real
  usage flowing back into the test set.

---

## Stack

Python · FastAPI · n8n · Qdrant · Ollama (mistral-small3.2, llama3.1, qwen2.5) ·
mxbai-embed-large · Typebot · PostgreSQL · Docker Compose · nginx · NVIDIA DGX Spark

---

## Running it

```bash
cp .env.example .env          # fill in the passwords
docker compose up -d          # n8n, Qdrant, PostgreSQL, Typebot, nginx

node scripts/ingest.mjs       # chunk + embed data/ into Qdrant
```

Inference expects an Ollama instance reachable from the compose network, with the chat
model and `mxbai-embed-large` pulled.

Then, in this order, because each one answers a different question:

```bash
bash scripts/audit_retrieval.sh "que modulos tiene DAW"   # what did retrieval return, with scores
bash scripts/rag_test.sh                                  # end-to-end without the orchestrator
python3 scripts/benchmark.py                              # the full 36-test suite
```

## Repository layout

| Path | What it is |
|---|---|
| `scripts/ingest.mjs` | Hierarchical chunking and embedding into Qdrant |
| `scripts/audit_retrieval.sh` | Retrieval-only diagnostic, prints chunks with scores |
| `scripts/rag_test.sh` | End-to-end RAG without n8n, reports answer and latency |
| `scripts/benchmark.py` | The evaluation suite |
| `workflows/` | n8n and Typebot workflow definitions |
| `docs/arquitectura.md` | Component and data-flow detail |
| `docs/historial-decisiones.md` | Decision log: problem, cause, decision, result |
| `docs/benchmark-resultados.md` | Eval results per model |
| `data/` | **Fictional** sample corpus (see note at the top) |

## Licence

The code is published as a portfolio piece. The knowledge base is fictional sample data.
