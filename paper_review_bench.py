#!/usr/bin/env python3
"""Build, run, and score a paper-review benchmark with no runtime dependencies."""

import argparse
import ast
import csv
import gzip
import hashlib
import json
import math
import os
import re
import statistics
import sys
import tarfile
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "1.0"
# ponytail: conservative length gate; replace with source-specific structural checks if short papers matter.
MIN_FULL_TEXT_CHARS = 10_000
CRITERIA = [
    {"name": "soundness", "description": "Technical correctness and validity of the evidence."},
    {"name": "contribution", "description": "Significance and usefulness of the contribution."},
    {"name": "novelty", "description": "Originality relative to prior work described in the paper."},
    {"name": "clarity", "description": "Clarity, organization, and precision of presentation."},
    {"name": "reproducibility", "description": "Sufficiency of methods, data, and experimental detail."},
]
MODEL_SCALE = {
    "min": 1,
    "max": 10,
    "anchors": {
        "1": "Fundamentally invalid or unsupported.",
        "3": "Major flaws substantially outweigh the strengths.",
        "5": "Mixed quality with substantial unresolved concerns.",
        "6": "Solid work with meaningful limitations.",
        "8": "Strong and technically sound contribution.",
        "10": "Exceptional contribution with no material weaknesses.",
    },
}
RUBRIC = {
    "name": "Unified scientific paper review rubric",
    "criteria": CRITERIA,
    "overall_score": MODEL_SCALE,
    "instruction": "Judge only evidence in the supplied paper. Do not infer the human score.",
}


def open_jsonl(path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8")


def rows(path):
    with open_jsonl(path) as source:
        for line_no, line in enumerate(source, 1):
            if line.strip():
                yield line_no, json.loads(line)


def mean(values):
    return statistics.fmean(values) if values else None


def normalize(value, low, high):
    return (value - low) / (high - low) if value is not None and high > low else None


def title_from_tex(text):
    match = re.search(r"\\title\{([^{}]+)\}", text, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def parsed_paper_text(value):
    metadata = (value.get("metadata") or value) if isinstance(value, dict) else {}
    parts = []
    for key in ("title", "abstractText", "abstract"):
        if metadata.get(key):
            parts.append(str(metadata[key]))
    for section in metadata.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading, text = section.get("heading"), section.get("text")
        if heading:
            parts.append(str(heading))
        if text:
            parts.append(str(text))
    return "\n\n".join(parts).strip()


def make_record(dataset, source_id, paper_text, title, scores, score_scale,
                split=None, locator=None,
                reference_locator=None, license_name=None):
    paper_text = str(paper_text).encode("utf-8", "replace").decode("utf-8")
    title = str(title or "").encode("utf-8", "replace").decode("utf-8")
    if not title.strip():
        title = next((line.strip()[:500] for line in paper_text.splitlines() if line.strip()), "Untitled")
    scores = [float(x) for x in scores]
    if not scores:
        raise ValueError(f"numeric human scores required: {dataset}:{source_id}")
    low, high = score_scale["min"], score_scale["max"]
    human_mean = mean(scores)
    canonical_id = f"openreview:{source_id}" if source_id else "sha256:" + hashlib.sha256(
        (title + "\n" + paper_text[:1000]).encode()
    ).hexdigest()
    identity = f"{canonical_id}|{split}"
    record_id = f"{dataset}:{hashlib.sha256(identity.encode()).hexdigest()[:20]}"
    return {
        "schema_version": SCHEMA_VERSION,
        "id": record_id,
        "canonical_id": canonical_id,
        "task": "paper_score",
        "source": {
            "dataset": dataset,
            "split": split,
            "record_id": source_id,
            "locator": locator,
            "reference_reasoning_locator": reference_locator,
            "license": license_name,
        },
        "paper": {"title": title, "text": paper_text},
        "rubric": RUBRIC,
        "human_evaluation": {
            "scores": scores,
            "score_scale": score_scale,
            "mean": human_mean,
            "median": statistics.median(scores),
            "std": statistics.pstdev(scores) if len(scores) > 1 else 0.0,
            "normalized_mean": normalize(human_mean, low, high),
            "review_count": len(scores),
        },
    }


def llmscore_records(corpora, limit=0):
    root = corpora / "LLMscore-ICLR-OpenReview-main"
    emitted = 0
    for year in (2023, 2024, 2025):
        data = root / "data" / f"ICLR_{year}"
        papers = {x["paper_id"]: x for _, x in rows(data / "papers.jsonl.gz")}
        scores = defaultdict(list)
        for _, review in rows(data / "reviews.jsonl.gz"):
            if review.get("actual_score") is not None and float(review["actual_score"]) > 0:
                scores[review["paper_id"]].append(float(review["actual_score"]))
        archive = root / "texts" / f"ICLR_{year}.tar.gz"
        with tarfile.open(archive, "r|gz") as source:
            for member in source:
                if not member.isfile() or not member.name.endswith(".txt"):
                    continue
                paper_id = Path(member.name).stem
                paper = papers.get(paper_id)
                if not paper or not scores.get(paper_id):
                    continue
                extracted = source.extractfile(member)
                if extracted is None:
                    continue
                text = extracted.read().decode("utf-8", errors="replace")
                yield make_record(
                    "LLMscore-ICLR-OpenReview", paper_id, text, paper.get("title", ""),
                    scores[paper_id], {"min": 1, "max": 10}, split=f"ICLR_{year}",
                    locator=f"{archive.relative_to(ROOT)}::{member.name}",
                    reference_locator=str((data / "reviews.jsonl.gz").relative_to(ROOT)),
                    license_name="CC-BY-4.0",
                )
                emitted += 1
                if limit and emitted >= limit:
                    return


def aaar_records(corpora, limit=0):
    root = corpora / "AAAR-1.0-hf" / "Paper_Weakness" / "ICLR_2023"
    for emitted, path in enumerate(sorted(root.glob("*/data_text.json")), 1):
        value = json.loads(path.read_text())
        matrix = ast.literal_eval(value.get("review_scores", "[]"))
        scores = [float(row[1]) for row in matrix if len(row) >= 2]
        text = parsed_paper_text(value.get("input", {}))
        if text and scores:
            yield make_record(
                "AAAR-1.0", value.get("ID"), text, value.get("Title", ""), scores,
                {"min": 1, "max": 10, "observed_values": [1, 3, 5, 6, 8, 10]},
                split=value.get("Conferece"),
                locator=str(path.relative_to(ROOT)), reference_locator=str(path.relative_to(ROOT)),
                license_name="MIT; dataset card prohibits training",
            )
        if limit and emitted >= limit:
            return


def deepreview_records(corpora, limit=0):
    root = corpora / "DeepReview-13K-hf" / "data"
    csv.field_size_limit(sys.maxsize)
    seen = set()
    emitted = 0
    for path in (root / "test_2024.csv", root / "test_2025.csv", root / "train.csv"):
        with path.open(newline="", encoding="utf-8") as source:
            for line_no, row in enumerate(csv.DictReader(source), 2):
                paper_id = row.get("id")
                if not paper_id or paper_id in seen:
                    continue
                seen.add(paper_id)
                try:
                    messages = json.loads(row["inputs"])
                    text = messages[-1]["content"]
                    scores = json.loads(row["rating"])
                except (KeyError, TypeError, json.JSONDecodeError):
                    continue
                yield make_record(
                    "DeepReview-13K", paper_id, text, title_from_tex(text), scores,
                    {"min": 1, "max": 10}, split=path.stem,
                    locator=f"{path.relative_to(ROOT)}:csv-row-{line_no}",
                    reference_locator=f"{path.relative_to(ROOT)}:csv-row-{line_no}:outputs",
                    license_name="DeepReviewer license; no formal-review use",
                )
                emitted += 1
                if limit and emitted >= limit:
                    return


ADAPTERS = (
    ("LLMscore-ICLR-OpenReview", llmscore_records),
    ("AAAR-1.0", aaar_records),
    ("DeepReview-13K", deepreview_records),
)


def build(args):
    corpora, output = Path(args.corpora).resolve(), Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    counts, candidates, duplicates_removed, incomplete_removed = Counter(), Counter(), Counter(), Counter()
    ids, seen_canonical = set(), set()
    missing = Counter()
    lengths, score_values = defaultdict(list), defaultdict(list)
    with gzip.open(partial, "wt", encoding="utf-8", compresslevel=1) as destination:
        for name, adapter in ADAPTERS:
            for record in adapter(corpora, args.max_per_source):
                candidates[name] += 1
                if len(record["paper"]["text"].strip()) < MIN_FULL_TEXT_CHARS:
                    incomplete_removed[name] += 1
                    continue
                if record["canonical_id"] in seen_canonical:
                    duplicates_removed[name] += 1
                    continue
                seen_canonical.add(record["canonical_id"])
                if record["id"] in ids:
                    raise ValueError(f"duplicate record id: {record['id']}")
                ids.add(record["id"])
                for field, value in (("title", record["paper"]["title"]),
                                     ("text", record["paper"]["text"]),
                                     ("locator", record["source"]["locator"])):
                    if not value:
                        missing[field] += 1
                if missing:
                    raise ValueError(f"required benchmark field missing: {record['id']} {dict(missing)}")
                values = record["human_evaluation"]["scores"]
                scale = record["human_evaluation"]["score_scale"]
                if not values or scale is None:
                    raise ValueError(f"numeric human scores required: {record['id']}")
                if min(values) < scale["min"] or max(values) > scale["max"]:
                    raise ValueError(f"score outside declared scale: {record['id']}")
                destination.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                counts[name] += 1
                lengths[name].append(len(record["paper"]["text"]))
                score_values[name].extend(values)
            print(f"{name}: {counts[name]}", flush=True)
    partial.replace(output)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "records": sum(counts.values()),
        "records_by_source": dict(counts),
        "candidate_records_by_source": dict(candidates),
        "incomplete_text_records_removed_by_source": dict(incomplete_removed),
        "duplicates_removed_by_source": dict(duplicates_removed),
        "unique_canonical_papers": len(seen_canonical),
        "duplicate_canonical_papers": 0,
        "cross_source_duplicates_removed": sum(duplicates_removed.values()),
        "output": str(output),
        "sha256": file_hash(output),
        "excluded_sources": {
            "PeerSum": "numeric ratings are present, but only the abstract is provided",
            "PeerRead": "full paper text is present, but no numeric human paper score is provided",
            "ReviewCritique": "full paper text is present, but no numeric human paper score is provided",
            "PRRCA": "reviews/rebuttals and scores are present, but full paper text is absent",
            "DISAPERE": "review/rebuttal discourse labels are present, but full paper text is absent",
            "ArgumentPairExtraction": "review/rebuttal passages are present, but full paper text and paper score are absent",
            "NLPeer": "dataset files require a separate manual access grant",
            "ASAP-Review": "official separately hosted data is unavailable locally",
            "AAAR Equation_Inference/Experiment_Design": "different tasks without a human overall paper score",
        },
        "quality_rules": [
            "Prompts contain paper.text and rubric only; human labels and reference reviews are never sent.",
            "LLMscore actual_score is human ground truth; expected_score and bias are excluded as LLM-derived leakage.",
            "LLMscore ICLR 2025 actual_score is uniformly 0, outside the valid scale, and is excluded as a missing-value sentinel.",
            "AAAR overall rating is review_scores column 2; columns 1 and 3 are soundness and confidence.",
            "Correlations use one paper-level mean human score, not one row per reviewer.",
            f"Every output record has source-designated paper text of at least {MIN_FULL_TEXT_CHARS} characters and at least one numeric human score.",
            "Canonical OpenReview paper IDs are unique; later duplicate occurrences are removed.",
        ],
        "quality_profile": {
            "duplicate_record_ids": 0,
            "duplicate_canonical_ids": 0,
            "missing_required_fields": dict(missing),
            "text_chars_p10_p50_p90": {name: percentiles(values) for name, values in lengths.items()},
            "human_score_range": {
                name: [min(values), max(values)] if values else None for name, values in score_values.items()
            },
        },
    }
    manifest_path = output.with_name("manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def percentiles(values):
    values = sorted(values)
    return [values[round((len(values) - 1) * q)] for q in (0.1, 0.5, 0.9)] if values else []


def endpoint_url(server):
    server = server.rstrip("/")
    if server.endswith("/chat/completions"):
        return server
    return server + ("/chat/completions" if server.endswith("/v1") else "/v1/chat/completions")


def prompt_for(record, max_input_chars=0):
    text = record["paper"]["text"]
    if max_input_chars and len(text) > max_input_chars:
        # ponytail: head+tail truncation is deterministic; use token-aware chunking when context studies require it.
        half = max_input_chars // 2
        text = text[:half] + "\n\n[... middle truncated ...]\n\n" + text[-half:]
    return (
        "Review the paper using the rubric. Return one JSON object only with keys: "
        "reasoning (object containing summary, strengths array, weaknesses array, and criterion_assessments array), "
        "and paper_score (number from 1 to 10). Do not mention or guess any hidden human rating.\n\n"
        f"RUBRIC:\n{json.dumps(record['rubric'], ensure_ascii=False)}\n\n"
        f"PAPER TITLE:\n{record['paper']['title']}\n\nPAPER:\n{text}"
    )


def parse_model_json(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model response is not a JSON object")
        value = json.loads(cleaned[start:end + 1])
    score = float(value["paper_score"])
    if not 1 <= score <= 10 or not isinstance(value.get("reasoning"), (dict, str)):
        raise ValueError("paper_score must be 1..10 and reasoning must be present")
    value["paper_score"] = score
    return value


def request_one(record, index, args):
    servers = args.server
    errors = []
    for attempt in range(args.retries + 1):
        server = servers[(index + attempt) % len(servers)]
        payload = {
            "model": args.model,
            "messages": [
                {"role": "system", "content": "You are a rigorous scientific peer reviewer."},
                {"role": "user", "content": prompt_for(record, args.max_input_chars)},
            ],
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            endpoint_url(server), json.dumps(payload).encode(),
            {"Content-Type": "application/json", "Authorization": f"Bearer {args.api_key}"},
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=args.timeout) as response:
                raw = json.load(response)
            content = raw["choices"][0]["message"]["content"]
            return {
                "id": record["id"], "canonical_id": record["canonical_id"],
                "source": record["source"]["dataset"], "model": args.model,
                "server": server, "output": parse_model_json(content),
            }
        except Exception as error:
            errors.append(f"{server}: {type(error).__name__}: {error}")
            if attempt < args.retries:
                time.sleep(min(2 ** attempt, 8))
    return {"id": record["id"], "canonical_id": record["canonical_id"], "error": errors}


def selected_records(args, completed):
    selected = 0
    for _, record in rows(Path(args.input)):
        if record["id"] in completed:
            continue
        if args.source and record["source"]["dataset"] not in args.source:
            continue
        yield record
        selected += 1
        if args.limit and selected >= args.limit:
            return


def run(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = set()
    if output.exists():
        for _, value in rows(output):
            completed.add(value.get("id"))
    records_to_run = iter(selected_records(args, completed))
    print(f"resumed={len(completed)} servers={len(args.server)} workers={args.workers}")
    with output.open("a", encoding="utf-8") as destination, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures, submitted, done = {}, 0, 0
        def submit_next():
            nonlocal submitted
            try:
                record = next(records_to_run)
            except StopIteration:
                return False
            future = pool.submit(request_one, record, submitted, args)
            futures[future] = record["id"]
            submitted += 1
            return True
        for _ in range(args.workers):
            if not submit_next():
                break
        while futures:
            future = next(as_completed(futures))
            futures.pop(future)
            result = future.result()
            destination.write(json.dumps(result, ensure_ascii=False) + "\n")
            destination.flush()
            done += 1
            submit_next()
            if done % 10 == 0 or not futures:
                print(f"completed={done} submitted={submitted}", flush=True)


def pearson(xs, ys):
    if len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    top = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    return top / math.sqrt(dx * dy) if dx and dy else None


def ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + j - 1) / 2 + 1
        for k in order[i:j]:
            result[k] = rank
        i = j
    return result


def spearman(xs, ys):
    return pearson(ranks(xs), ranks(ys)) if len(xs) >= 2 else None


def kendall_tau_b(xs, ys):
    if len(xs) < 2:
        return None
    ys_unique = {v: i + 1 for i, v in enumerate(sorted(set(ys)))}
    tree = [0] * (len(ys_unique) + 1)
    def add(i):
        while i < len(tree):
            tree[i] += 1
            i += i & -i
    def query(i):
        total = 0
        while i:
            total += tree[i]
            i -= i & -i
        return total
    pairs = sorted(zip(xs, ys))
    concordant = discordant = tied_x = tied_y = seen = 0
    i = 0
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        group = pairs[i:j]
        by_y = Counter(y for _, y in group)
        tied_x += len(group) * (len(group) - 1) // 2 - sum(n * (n - 1) // 2 for n in by_y.values())
        for _, y in group:
            rank = ys_unique[y]
            less, leq = query(rank - 1), query(rank)
            concordant += less
            discordant += seen - leq
            tied_y += leq - less
        for _, y in group:
            add(ys_unique[y])
            seen += 1
        i = j
    denom = math.sqrt((concordant + discordant + tied_x) * (concordant + discordant + tied_y))
    return (concordant - discordant) / denom if denom else None


def fisher_ci(r, n):
    if r is None or n <= 3 or abs(r) >= 1:
        return None
    z, delta = math.atanh(r), 1.96 / math.sqrt(n - 3)
    return [math.tanh(z - delta), math.tanh(z + delta)]


def metric_block(pairs):
    human = [x[0] for x in pairs]
    model = [x[1] for x in pairs]
    pr, sr = pearson(human, model), spearman(human, model)
    return {
        "n": len(pairs), "pearson_r": pr, "pearson_95ci": fisher_ci(pr, len(pairs)),
        "spearman_rho": sr, "spearman_approx_95ci": fisher_ci(sr, len(pairs)),
        "kendall_tau_b": kendall_tau_b(human, model),
        "normalized_mae": mean([abs(a - b) for a, b in zip(human, model)]),
        "normalized_rmse": math.sqrt(mean([(a - b) ** 2 for a, b in zip(human, model)])) if pairs else None,
    }


def score(args):
    records_by_id = {
        record["id"]: {
            "canonical_id": record["canonical_id"],
            "source": record["source"]["dataset"],
            "human": record["human_evaluation"],
        }
        for _, record in rows(Path(args.input))
    }
    numeric = defaultdict(list)
    reviewer_halves = defaultdict(lambda: [[], []])
    errors = total = 0
    for _, result in rows(Path(args.results)):
        total += 1
        record = records_by_id.get(result.get("id"))
        if not record or result.get("error") or "output" not in result:
            errors += 1
            continue
        predicted = normalize(float(result["output"]["paper_score"]), 1, 10)
        human = record["human"]
        source = record["source"]
        if human.get("normalized_mean") is not None:
            pair = (float(human["normalized_mean"]), predicted)
            numeric[source].append(pair)
            numeric["__pooled__"].append(pair)
            values = human.get("scores", [])
            if len(values) >= 2:
                low, high = human["score_scale"]["min"], human["score_scale"]["max"]
                reviewer_halves[source][0].append(normalize(mean(values[::2]), low, high))
                reviewer_halves[source][1].append(normalize(mean(values[1::2]), low, high))
    metrics = {
        "primary_metric": "spearman_rho on paper-level mean human score",
        "co_primary_metric": "pearson_r on normalized paper-level mean human score",
        "completed_results": total - errors,
        "failed_or_unmatched_results": errors,
        "numeric": {name: metric_block(pairs) for name, pairs in numeric.items()},
        "human_split_half_reliability": {
            name: {
                "n": len(groups[0]), "pearson_r": pearson(*groups), "spearman_rho": spearman(*groups),
            } for name, groups in reviewer_halves.items()
        },
        "notes": [
            "Scores from every source are min-max normalized before pooled metrics.",
            "Correlations measure association; normalized MAE/RMSE measure calibration.",
            "Fisher intervals are analytic approximations and do not account for dataset clustering.",
            "Human split-half reliability is a diagnostic ceiling, not an ICC estimate.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def self_test():
    assert pearson([1, 2, 3], [2, 4, 6]) == 1.0
    assert spearman([10, 20, 20, 30], [1, 2, 2, 3]) == 1.0
    assert kendall_tau_b([1, 2, 3], [1, 2, 3]) == 1.0
    assert kendall_tau_b([1, 2, 3], [3, 2, 1]) == -1.0
    parsed = parse_model_json('{"reasoning":{"summary":"ok"},"paper_score":7}')
    assert parsed["paper_score"] == 7.0
    record = make_record("test", "x", "bad \ud835", "", [5], {"min": 1, "max": 10})
    assert record["paper"]["text"].encode("utf-8") and record["paper"]["title"]
    assert not ({"decision", "accepted"} & record["human_evaluation"].keys())
    assert "recommendation" not in prompt_for(record)
    assert parsed_paper_text({"metadata": {"title": "Only title", "sections": None}}) == "Only title"
    print("self-test passed")


def parser():
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    p = commands.add_parser("build")
    p.add_argument("--corpora", default=ROOT / "corpora")
    p.add_argument("--output", default=ROOT / "benchmark_data" / "records.jsonl.gz")
    p.add_argument("--max-per-source", type=int, default=0, help="0 means all")
    p.set_defaults(func=build)
    p = commands.add_parser("run")
    p.add_argument("--input", default=ROOT / "benchmark_data" / "records.jsonl.gz")
    p.add_argument("--output", default=ROOT / "results" / "predictions.jsonl")
    p.add_argument("--server", action="append", required=True, help="repeat for multiple vLLM/OpenAI-compatible servers")
    p.add_argument("--model", required=True)
    p.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", "EMPTY"))
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-input-chars", type=int, default=0, help="0 preserves the full paper")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--source", action="append")
    p.set_defaults(func=run)
    p = commands.add_parser("score")
    p.add_argument("--input", default=ROOT / "benchmark_data" / "records.jsonl.gz")
    p.add_argument("--results", default=ROOT / "results" / "predictions.jsonl")
    p.add_argument("--output", default=ROOT / "results" / "metrics.json")
    p.set_defaults(func=score)
    p = commands.add_parser("self-test")
    p.set_defaults(func=lambda _: self_test())
    return top


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
