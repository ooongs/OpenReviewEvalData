# Paper Review Benchmark

This benchmark gives an LLM only a scientific paper and a common review rubric.
The required output is structured reasoning plus a score from 1 to 10. Hidden
human ratings are joined only after inference.

## Build the unified JSONL

```bash
python3 paper_review_bench.py self-test
python3 paper_review_bench.py build
```

The full output is `benchmark_data/records.jsonl.gz`; `manifest.json` records
source counts, exclusions, duplicate canonical papers, and leakage controls.
Every JSONL record uses the same `paper`, `rubric`, `human_evaluation`, and
`source` fields. Large generated data and results are Git-ignored.

The scored full-paper track uses LLMscore, AAAR Paper Weakness, and DeepReview.
PeerRead and ReviewCritique add acceptance-only full-paper records. PeerSum is
kept as an explicitly tagged `abstract` track. Corpora without paper text or a
paper-level label remain listed in the manifest rather than being silently
forced into an invalid task.

The verified local build contains 53,582 source records and 47,978 canonical
papers. The default deduplicated full-text numeric track contains 20,675 papers;
the compressed JSONL is 752 MB. Exact source counts, score ranges, text-length
quantiles, exclusions, and its SHA-256 are in `benchmark_data/manifest.json`.

## Run locally with vLLM

Start a server using a context length appropriate for full papers:

```bash
vllm serve Qwen/Qwen3-32B \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 2 --max-model-len 65536
```

Run a resumable batch. The output is flushed after every completed request:

```bash
python3 paper_review_bench.py run \
  --server http://127.0.0.1:8000/v1 \
  --model Qwen/Qwen3-32B --workers 8 \
  --task paper_score --full-text-only
```

Repeat `--server` to distribute requests across replicas or hosts. Failed
requests retry on the next server; restarting the same command skips completed
record IDs. Concurrent HTTP requests feed vLLM's continuous batching without a
second queueing system.

```bash
python3 paper_review_bench.py run \
  --server http://gpu-a:8000/v1 \
  --server http://gpu-b:8000/v1 \
  --server http://gpu-c:8000/v1 \
  --model Qwen/Qwen3-32B --workers 24
```

`--max-input-chars` is available for models with a shorter context window. Its
default is `0`, which never truncates the paper.

## Score against humans

```bash
python3 paper_review_bench.py score
```

The scorer reports pooled and per-source Spearman, Pearson, Kendall tau-b,
normalized MAE/RMSE, acceptance ROC-AUC, and a human split-half reliability
diagnostic. All human scales are normalized to `[0, 1]` before pooling.

## Leakage and licensing

- Prompts contain only `paper` and `rubric`; human scores, decisions, reviews,
  and reference reasoning are never sent.
- `LLMscore.expected_score` and `bias` are excluded because they are LLM-derived.
- LLMscore ICLR 2025 zero-valued `actual_score` sentinels are excluded because
  zero is outside the source's human rating scale.
- DeepReviewer data may not be used for formal reviews.
- AAAR and ReviewCritique prohibit training use in their accompanying terms.
- Upstream licenses and usage restrictions remain controlling.
