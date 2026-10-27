# End-to-end agent evaluation

Model: **fake-deterministic-1** (fake). Questions: 32.

| Metric | Value |
|---|---|
| Answer contains every expected fact | 0.875 |
| Cites a relevant document | 0.969 |
| p50 workflow latency (ms) | 11.5 |

Failed questions:

- `q07` Above what amount do I need to attach a receipt?
- `q10` Who has to approve a purchase of 30,000 euros?
- `q24` Where is the company headquartered and how many people work there?
- `q25` By which year does the company want to be net-zero?

Reproduce: `python -m aistack.eval.agent_eval`. With the default deterministic model the answerer
is extractive, so this validates the pipeline, not language-model quality.
