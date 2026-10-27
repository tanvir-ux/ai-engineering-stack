# Retrieval evaluation report

Golden set: **32 questions** over **65 chunks** from 28 synthetic documents (`evals/golden.jsonl`). Each question names the document that holds the answer. Questions are asked as a role that is allowed to read that document.

Reproduce: `make eval`

| Retriever | hit@1 | hit@3 | hit@5 | MRR | answer text in top-3 context | p50 latency (ms) |
|---|---|---|---|---|---|---|
| bm25 | 0.969 | 1.000 | 1.000 | 0.984 | 0.969 | 0.04 |
| dense (hashing embeddings) | 0.719 | 0.938 | 0.938 | 0.818 | 0.875 | 0.05 |
| hybrid (RRF) | 0.938 | 1.000 | 1.000 | 0.964 | 0.969 | 0.08 |
| hybrid (RRF) + rerank | 0.969 | 1.000 | 1.000 | 0.979 | 0.969 | 0.32 |

## Access-control check

Every golden question was asked as each of 5 roles (160 searches). Forbidden chunks returned: **0**. Questions whose answer lives in a document the role may not read: 53, of which the document was correctly withheld in **53**.

## Notes and limits

- The default embedder is a feature-hashing embedder (lexical, no neural model), so "dense" here is a lexical vector baseline. Swap in real embeddings (`OpenAIEmbedder`) to compare.
- The golden set is small and synthetic. Treat the numbers as a regression gate and a demonstration of the method, not as a general benchmark.
- The reranker is a transparent heuristic, not a cross-encoder.
