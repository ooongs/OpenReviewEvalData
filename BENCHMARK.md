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
source counts, exclusions, removed duplicates, and leakage controls.
Every JSONL record uses the same `paper`, `rubric`, `human_evaluation`, and
`source` fields. Large generated data and results are Git-ignored.

Every record has a numeric human paper score, at least 10,000 characters of
source-designated full paper text, and a unique canonical OpenReview paper ID.
The benchmark uses LLMscore, AAAR Paper Weakness, and DeepReview. Abstract-only,
categorical-label-only, and incomplete-text records are excluded and documented
in the manifest.

The verified build contains 20,557 unique papers: 10,603 from LLMscore, 86 from
AAAR, and 9,868 from DeepReview. It removes 5,566 duplicate occurrences and 162
incomplete-text occurrences from 26,285 candidates. The compressed JSONL is
497,029,732 bytes. Exact score ranges, text-length quantiles, exclusions, and
the file's SHA-256 are in `benchmark_data/manifest.json`.

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
  --model Qwen/Qwen3-32B --workers 8
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
normalized MAE/RMSE, and a human split-half reliability diagnostic. All human
scales are normalized to `[0, 1]` before pooling.

## Leakage and licensing

- Prompts contain only `paper` and `rubric`; human scores, reviews, and reference
  reasoning are never sent.
- `LLMscore.expected_score` and `bias` are excluded because they are LLM-derived.
- LLMscore ICLR 2025 zero-valued `actual_score` sentinels are excluded because
  zero is outside the source's human rating scale.
- DeepReviewer data may not be used for formal reviews.
- AAAR prohibits training use in its accompanying terms.
- Upstream licenses and usage restrictions remain controlling.
