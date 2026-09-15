# Metric selection

## Selected measures

The benchmark uses the **paper-level mean human rating** as its numeric target.
Reviewer rows are not treated as independent papers. Source-specific scales and
model scores are min-max normalized before any pooled calculation.

1. **Spearman's rho (primary):** review scales are discrete and ordinal, so
   ranking agreement is the least assumption-heavy main measure.
2. **Pearson's r (co-primary):** directly measures linear agreement with the
   human mean and matches the project's stated human-correlation target.
3. **Kendall's tau-b:** a tie-aware rank statistic, important because ICLR
   ratings use a small set of repeated values.
4. **Normalized MAE and RMSE:** correlation can be high despite systematically
   inflated or deflated scores; these report calibration error.
5. **ROC-AUC:** secondary measure for corpora exposing accept/reject rather than
   a numeric rating.
6. **Human split-half correlation:** reports label noise/reliability as a useful
   ceiling for interpreting model-human correlation.

No arbitrary composite “overall score” is introduced. A composite can hide a
model that ranks papers correctly but is badly calibrated. For model comparison,
report primary Spearman and co-primary Pearson with their confidence intervals,
then use MAE and per-source results as guardrails.

## Research basis

- Kendall, M. G. (1945), *The Treatment of Ties in Ranking Problems*, introduced
  the tie-corrected tau formulation used here: https://doi.org/10.1093/biomet/33.3.239
- Pearson correlation quantifies linear association; Spearman correlation is
  Pearson correlation over ranks. SciPy's statistical reference documents the
  assumptions and interpretation: https://docs.scipy.org/doc/scipy/reference/stats.html
- Shrout and Fleiss (1979) established ICC variants for rater reliability:
  https://doi.org/10.1037/0033-2909.86.2.420. This first release reports a
  dependency-free split-half diagnostic; confirmatory studies should add a
  pre-specified ICC model.
- PeerRead defines accept/reject prediction as a scientific-review task:
  https://aclanthology.org/N18-1149/
- AAAR-1.0 evaluates paper weakness identification separately from equation and
  experiment tasks: https://arxiv.org/abs/2410.22394
- DeepReview supplies structured review reasoning, ratings, and decisions but
  explicitly restricts formal-review use: https://arxiv.org/abs/2503.08569

## Known risks

- Venue/year score distributions differ; always inspect per-source metrics in
  addition to pooled metrics.
- LLMscore ICLR 2025 stores `actual_score=0` for every record, outside its
  1–10 scale. These sentinel values are excluded rather than treated as ratings.
- The mean rating reduces reviewer noise but does not make subjective labels
  objective. Report review count, dispersion, and split-half reliability.
- Published papers may be present in model pretraining data. Results are model
  familiarity plus review ability unless a time-controlled subset is used.
- PeerSum contains abstracts rather than full papers and is therefore reported
  as a separate short-context stratum.
