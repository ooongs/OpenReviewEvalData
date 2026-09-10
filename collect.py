#!/usr/bin/env python3
"""Collect a small ICLR paper/review/text sample without extra packages."""

import argparse
import gzip
import hashlib
import json
import math
import shutil
import tarfile
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = "wutaghost/LLMscore-ICLR-OpenReview"
ROOT = Path(__file__).resolve().parent


def request(url, data=None, headers=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = {"User-Agent": "OpenReviewEvalData", **(headers or {})}
    return opener.open(urllib.request.Request(url, data=data, headers=base), timeout=300)


def github_file(remote_path, destination):
    if destination.exists():
        return
    url = f"https://api.github.com/repos/{REPO}/contents/{remote_path}?ref=main"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with request(url, headers={"Accept": "application/vnd.github.raw+json"}) as src:
        with destination.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def text_archive(year, destination):
    if destination.exists():
        return
    pointer_url = (
        f"https://api.github.com/repos/{REPO}/contents/texts/ICLR_{year}.tar.gz?ref=main"
    )
    with request(pointer_url, headers={"Accept": "application/vnd.github.raw+json"}) as src:
        pointer = src.read().decode()
    oid = next(line.split(":", 1)[1] for line in pointer.splitlines() if line.startswith("oid "))
    size = int(next(line.split()[1] for line in pointer.splitlines() if line.startswith("size ")))
    payload = json.dumps(
        {"operation": "download", "transfers": ["basic"], "objects": [{"oid": oid, "size": size}]}
    ).encode()
    batch_url = f"https://github.com/{REPO}.git/info/lfs/objects/batch"
    with request(
        batch_url,
        payload,
        {"Accept": "application/vnd.git-lfs+json", "Content-Type": "application/vnd.git-lfs+json"},
    ) as src:
        download_url = json.load(src)["objects"][0]["actions"]["download"]["href"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    with request(download_url) as src, partial.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    if partial.stat().st_size != size or sha256(partial) != oid:
        partial.unlink(missing_ok=True)
        raise RuntimeError("Downloaded text archive failed size or SHA-256 validation")
    partial.replace(destination)


def rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def choose_papers(papers, reviews_by_paper, text_ids, sample_size):
    buckets = defaultdict(list)
    for paper in papers:
        reviews = reviews_by_paper.get(paper["paper_id"], [])
        if paper["paper_id"] in text_ids and paper["avg_actual_score"] is not None and reviews:
            buckets[round(paper["avg_actual_score"])].append(paper)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: row["paper_id"])
    selected = []
    for offset in range(math.ceil(sample_size / max(len(buckets), 1))):
        for score in sorted(buckets):
            if offset < len(buckets[score]) and len(selected) < sample_size:
                selected.append(buckets[score][offset])
    return selected


def dump_jsonl(path, values):
    with path.open("w", encoding="utf-8") as output:
        for value in values:
            output.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def collect(year, sample_size):
    cache = ROOT / ".cache" / f"ICLR_{year}"
    output = ROOT / "data" / f"iclr_{year}_sample"
    source_files = {
        name: cache / f"{name}.jsonl.gz" for name in ("papers", "reviews", "paper_text_index")
    }
    for name, destination in source_files.items():
        github_file(f"data/ICLR_{year}/{name}.jsonl.gz", destination)
    archive = cache / f"ICLR_{year}.tar.gz"
    text_archive(year, archive)

    all_reviews = list(rows(source_files["reviews"]))
    reviews_by_paper = defaultdict(list)
    for review in all_reviews:
        if review.get("actual_score") is not None:
            reviews_by_paper[review["paper_id"]].append(review)
    text_index = {row["paper_id"]: row for row in rows(source_files["paper_text_index"])
                  if row.get("conversion_status") == "ok" and row.get("text_path")}
    selected = choose_papers(rows(source_files["papers"]), reviews_by_paper, set(text_index), sample_size)
    if len(selected) != sample_size:
        raise RuntimeError(f"Requested {sample_size} papers, found {len(selected)} eligible papers")

    output.mkdir(parents=True, exist_ok=True)
    texts = output / "texts"
    texts.mkdir(exist_ok=True)
    for stale in texts.glob("*.txt"):
        stale.unlink()
    selected_ids = {paper["paper_id"] for paper in selected}
    with tarfile.open(archive, "r:gz") as source:
        for paper_id in sorted(selected_ids):
            _, member = text_index[paper_id]["text_path"].split("::", 1)
            extracted = source.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"Missing text archive member: {member}")
            (texts / f"{paper_id}.txt").write_bytes(extracted.read())

    selected_reviews = [review for review in all_reviews if review["paper_id"] in selected_ids]
    dump_jsonl(output / "papers.jsonl", selected)
    dump_jsonl(output / "reviews.jsonl", selected_reviews)
    rubric = {
        "conference": f"ICLR {year}",
        "provenance": "Observed labels in the released review records; not inferred descriptions.",
        "reviewer_guide": f"https://iclr.cc/Conferences/{year}/ReviewerGuide",
        "fields": {
            field: sorted({str(row[field]) for row in selected_reviews if row.get(field) is not None})
            for field in ("soundness", "presentation", "contribution", "confidence", "actual_score")
        },
        "text_fields": ["summary", "strengths", "weaknesses", "questions", "review_text"],
    }
    (output / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False, indent=2) + "\n")
    files = sorted(path for path in output.rglob("*") if path.is_file())
    manifest = {
        "source": f"https://github.com/{REPO}",
        "source_license": "CC-BY-4.0",
        "year": year,
        "papers": len(selected),
        "reviews": len(selected_reviews),
        "texts": len(list(texts.glob("*.txt"))),
        "files": {str(path.relative_to(output)): sha256(path) for path in files},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def self_test():
    papers = [
        {"paper_id": "a", "avg_actual_score": 3.0},
        {"paper_id": "b", "avg_actual_score": 8.0},
        {"paper_id": "c", "avg_actual_score": None},
    ]
    chosen = choose_papers(papers, {"a": [{}], "b": [{}]}, {"a", "b", "c"}, 2)
    assert [row["paper_id"] for row in chosen] == ["a", "b"]
    print("self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2024, choices=(2023, 2024, 2025))
    parser.add_argument("--sample-size", type=int, default=48)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error("--sample-size must be positive")
    self_test() if args.self_test else collect(args.year, args.sample_size)
