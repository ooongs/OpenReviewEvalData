# Dataset inventory

Large corpora live under the ignored `corpora/` directory. `datasets.json` is
the machine-readable inventory; upstream terms still govern every corpus.

## Downloaded data

| Dataset | Local records | Evaluation signal | License |
| --- | ---: | --- | --- |
| LLMscore-ICLR-OpenReview | 22,177 papers; 52,369 reviews; 22,675 texts | criterion/overall scores, confidence, rationale items | CC-BY-4.0 |
| PeerRead | 12,364 paper records; 7,584 embedded reviews | review text and accept/reject labels | varies by subset |
| ReviewCritique | 100 human-review papers; 20 LLM-review papers | expert segment-level deficiency labels | evaluation only; no training |
| PRRCA | 6,138 submissions | ratings, rebuttals, review-quality judgments, decisions, meta-reviews | unspecified upstream |
| DISAPERE | 506 review/rebuttal pairs | 9,946 review and 11,103 rebuttal sentences with discourse/alignment labels | CC-BY-NC-4.0 |
| Argument Pair Extraction | 4,760 review/rebuttal passage pairs | argument spans and review-to-rebuttal pair labels | unspecified upstream |

## Located but not automatically downloadable here

| Dataset | Published size | Reason |
| --- | ---: | --- |
| PeerSum | 14,993 | official Google Drive and Hugging Face endpoints unreachable |
| NLPeer v1/v2 | multiple ARR, ACL, COLING, CONLL, F1000, PLOS and eLife subsets | manual TU DataLib request required |
| DeepReview-13K | 13,378 training records | Hugging Face endpoint unreachable |
| AAAR-1.0 | see dataset card | Hugging Face endpoint unreachable |
| ASAP-Review / ReviewAdvisor | see paper | official Google Drive endpoint unreachable |

“Code downloaded” in `datasets.json` means the official repository and its
documentation are local, not that a separately hosted dataset is present.
