# D42 — Hybrid recall with local embeddings + keyword search
Status: replaced by D50 · 30 Sep 2026 — **parked, not rejected**: the design below is kept for when it's needed.

## Context
Simba's memory (facts, chat summaries) needs recall: find the fact or past chat a message refers to.
Designed on 30 Sep (#79); replaced the same day, before any code, by D50 — index in the prompt +
keyword search, no embedding model — because Simba's memory is small (≤ 200 facts, one summary per
chat) and Claude itself matches meaning when it reads the index, the way Claude Code's memory works.

## Decision (as designed, not built)
- `recall_memory(query)` searches facts and chat summaries two ways at once:
  - **Keywords:** SQLite FTS5, ranked by BM25 (rare shared words weigh more). Good at names, numbers,
    exact terms; blind to synonyms.
  - **Embeddings:** a small local model (e.g. a MiniLM / bge-small class model, ~90 MB, 384 numbers per
    text, ONNX on CPU like the injection classifier) turns each text into a vector; cosine similarity
    finds texts with similar meaning ("vacation" ≈ "trip to Lisbon"). Vectors are computed when a fact
    or summary is saved and stored next to it; a search embeds only the query.
- **Merge:** reciprocal rank fusion — each result scores `1 / (60 + rank)` in each list, scores add up,
  so what ranks well in both comes first; no weights to tune.
- Results fenced as data; top 5; trace line per recall; tests use a fake embedder (CI never downloads).

## Consequences (if revived)
Good: finds things by meaning without Claude having to guess the right words; scales to thousands of
items. Bad: a second model to download (~90 MB), keep updated and explain; more code; embeddings of
every fact and summary to keep in sync.

## When to revisit
- Memory grows past what one index line per item can cover (hundreds of chats), or
- a memory eval shows recall missing things by meaning that a second keyword try doesn't find.
Revival ticket: see the "Future: vector recall" issue linked from #83.
