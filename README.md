# OpenReviewEvalData

Small, reproducible ICLR peer-review dataset for long-form evaluation research.

The checked-in sample contains 48 ICLR 2024 papers with:

- extracted paper text;
- paper metadata and OpenReview source URLs;
- public review text, overall scores, criterion scores, and confidence;
- a rubric reconstructed from the score labels observed in the review records.

## Build

Python 3.10+ is enough. No package installation is required.

```bash
python3 collect.py --year 2024 --sample-size 48
python3 collect.py --self-test
```

The first command downloads the source files to `.cache/` and writes the
GitHub-sized sample to `data/iclr_2024_sample/`. Re-running it is idempotent.

## Output

```text
data/iclr_2024_sample/
  papers.jsonl       # paper metadata and evaluation aggregates
  reviews.jsonl      # public review text and scores
  rubric.json        # observed review-form fields and scales
  manifest.json      # counts, hashes, and provenance
  texts/{paper_id}.txt
```

The source export does not include final accept/reject decisions. Here,
"evaluation results" means public reviewer scores, criterion scores,
confidence, and paper-level score aggregates. Decisions must not be inferred
from scores.

## Provenance and license

Data is sampled from
[`wutaghost/LLMscore-ICLR-OpenReview`](https://github.com/wutaghost/LLMscore-ICLR-OpenReview),
a CC-BY-4.0 release derived from public OpenReview-linked ICLR 2023–2025 data.
Original content remains attributable to OpenReview, ICLR, the papers, and
their reviewers. See the upstream license and original source terms before
redistributing a larger export.

The collection script is released under the MIT License.

