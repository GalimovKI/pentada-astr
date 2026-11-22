<h1 align="center"><img src="docs/assets/smartmail-logo.svg" width="310" alt="SmartMail"></h1>

<p align="center"><strong>Find an email even if you only remember what it was about.</strong><br>
SmartMail took <strong>second place at the MIPT Hackathon</strong> with its entry for VK Tech’s email search challenge.</p>

<p align="center"><a href="https://smartmail-hackaton.ru/main/"><strong>Try SmartMail ↗</strong></a></p>

## Recommended search engine

**Use event-aware BM25 (`bm25-event-aware`) for email search.** It powers the live site, runs on CPU, and achieved the highest **nDCG@10 (0.9976)** of the nine engines evaluated on the 99 public queries in Mail Public. [Configuration](configs/search/bm25-event-aware.json) · [Run instructions](EVAL.md#9-основной-метод-поиска) · [Run metrics](https://github.com/GalimovKI/pentada-astr/blob/team-memory/experiments/20261122T123953Z-6968d61e/candidate/public/metrics.json)

<p align="center"><a href="https://smartmail-hackaton.ru/main/"><img src="docs/assets/search-demo.gif" width="880" alt="SmartMail demo showing a user selecting the customer orders mailbox, correcting a typo in the search field, and opening a matching email."></a></p>

## Search quality

The development benchmarks use Mail Public, a corpus of 16,376 emails.

| Search engine | Recall@10 | nDCG@10 | MRR@10 |
|---|---:|---:|---:|
| **Event-aware BM25** | **0.9376** | **0.9976** | **1.0000** |
| BM25 + E5 (reciprocal rank fusion) | 0.9366 | 0.9949 | 1.0000 |
| E5 → BM25 | 0.9342 | 0.9935 | 0.9949 |
| Date-aware BM25 + MiniLM (75/25, ARM64 INT8) | 0.9366 | 0.9931 | 0.9949 |
| Query-weighted BM25 | 0.8648 | 0.9173 | 0.9848 |
| BM25 with stemming | 0.8615 | 0.8910 | 0.9444 |
| BM25 → E5 | 0.8547 | 0.8895 | 0.9163 |
| Baseline BM25 | 0.4441 | 0.4097 | 0.4590 |
| E5 with cosine similarity (INT8) | 0.2961 | 0.2004 | 0.2245 |

<details>
<summary>E5 and MiniLM latency on CPU and GPU</summary>

The development API processed 99 sequential queries with a limit of 100 emails per query and no separate warm-up. Times are in milliseconds. The CPU was an Intel Xeon Gold 6338 and the GPU was an NVIDIA A100 80 GB PCIe.

| Search engine | CPU p50 | CPU p99 | GPU p50 | GPU p99 |
|---|---:|---:|---:|---:|
| E5 with cosine similarity | 29.72 | 184.76 | 16.77 | 109.04 |
| Date-aware BM25 + MiniLM | 816.34 | 2,422.42 | 43.24 | 685.47 |

</details>

[Evaluation methodology](EVAL.md) · [EnronQA comparison](https://github.com/GalimovKI/pentada-astr/blob/e3781b900d3badfc0fe94c13f7336962c3633433/reports/quality/e5-hybrids.md) · [Deployment](DEPLOYMENT.md) · [Architecture](COMPONENTS.md)
