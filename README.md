# OpenReviewEvalData

Reproducible scientific-paper review data for long-form evaluation research.
The repository contains a small checked-in sample; the local ignored
`corpora/` directory contains the large published datasets listed in
[`DATASETS.md`](DATASETS.md).

The checked-in sample contains 48 ICLR 2024 papers with:

- extracted paper text;
- paper metadata and OpenReview source URLs;
- public review text, overall scores, criterion scores, and confidence;
- a rubric reconstructed from the score labels observed in the review records.

## Rebuild the checked-in sample

Python 3.10+ is enough. No package installation is required.

```bash
python3 collect.py --year 2024 --sample-size 48
python3 collect.py --self-test
```

The first command downloads the source files to `.cache/` and writes the
GitHub-sized sample to `data/iclr_2024_sample/`. Re-running it is idempotent.

## Collect directly from OpenReview

The official `openreview-py` client can preserve raw submissions, reviews,
rebuttals, meta-reviews, decisions, and the Invitations that define the actual
review-form rubrics:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python collect_openreview.py \
  --submission-invitation ICLR.cc/2024/Conference/-/Submission \
  --venue-id ICLR.cc/2024/Conference \
  --output corpora/openreview/iclr_2024
```

Set `OPENREVIEW_USERNAME` and `OPENREVIEW_PASSWORD` if the venue requires
authentication. Add `--limit 10` for a smoke test; the default downloads all
submissions. OpenReview currently returns a Cloudflare challenge from this
host, so the published exports below are the completed local source.

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

## Published corpora

`datasets.json` records source URLs, publication names, local paths, counts,
licenses, and acquisition status. Large data is intentionally Git-ignored and
currently occupies about 3.0 GB locally.

## Provenance and license

Data is sampled from
[`wutaghost/LLMscore-ICLR-OpenReview`](https://github.com/wutaghost/LLMscore-ICLR-OpenReview),
a CC-BY-4.0 release derived from public OpenReview-linked ICLR 2023–2025 data.
Original content remains attributable to OpenReview, ICLR, the papers, and
their reviewers. See the upstream license and original source terms before
redistributing a larger export.

The collection script is released under the MIT License.
