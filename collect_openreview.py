#!/usr/bin/env python3
"""Download submissions, forum notes, and review-form rubrics with openreview-py."""

import argparse
import json
import os
from pathlib import Path

import openreview


def as_json(value):
    return value.to_json() if hasattr(value, "to_json") else value


def write_jsonl(path, values):
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", encoding="utf-8") as output:
        for value in values:
            output.write(json.dumps(as_json(value), ensure_ascii=False, sort_keys=True) + "\n")
    partial.replace(path)


def collect(args):
    client = openreview.api.OpenReviewClient(
        baseurl=args.baseurl,
        username=os.getenv("OPENREVIEW_USERNAME"),
        password=os.getenv("OPENREVIEW_PASSWORD"),
    )
    submissions = client.get_all_notes(invitation=args.submission_invitation)
    submissions.sort(key=lambda note: note.id)
    if args.limit:
        submissions = submissions[: args.limit]

    submission_ids = {note.id for note in submissions}
    if args.venue_id and not args.limit:
        venue_notes = client.get_all_notes(domain=args.venue_id)
        forum_notes = {
            note.id: note
            for note in venue_notes
            if note.id in submission_ids or note.forum in submission_ids
        }
    else:
        forum_notes = {}
        for index, submission in enumerate(submissions, 1):
            for note in client.get_all_notes(forum=submission.id):
                forum_notes[note.id] = note
            print(f"forums {index}/{len(submissions)}", end="\r", flush=True)

    invitation_ids = sorted({
        invitation
        for note in forum_notes.values()
        for invitation in (getattr(note, "invitations", None) or [])
    })
    if args.venue_id:
        venue_invitations = {
            invitation.id: invitation
            for invitation in client.get_all_invitations(prefix=args.venue_id)
        }
        rubrics = [venue_invitations[i] for i in invitation_ids if i in venue_invitations]
        missing = [i for i in invitation_ids if i not in venue_invitations]
    else:
        rubrics, missing = [], []
        for invitation_id in invitation_ids:
            try:
                rubrics.append(client.get_invitation(id=invitation_id))
            except openreview.OpenReviewException:
                missing.append(invitation_id)

    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "submissions.jsonl", submissions)
    write_jsonl(args.output / "forum_notes.jsonl", sorted(forum_notes.values(), key=lambda n: n.id))
    write_jsonl(args.output / "rubrics.jsonl", rubrics)
    manifest = {
        "baseurl": args.baseurl,
        "submission_invitation": args.submission_invitation,
        "venue_id": args.venue_id,
        "submissions": len(submissions),
        "forum_notes": len(forum_notes),
        "rubrics": len(rubrics),
        "missing_invitation_ids": missing,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(" " * 40, end="\r")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def self_test():
    class Item:
        def to_json(self):
            return {"id": "ok"}

    assert as_json(Item()) == {"id": "ok"}
    assert as_json({"id": "raw"}) == {"id": "raw"}
    print("self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-invitation")
    parser.add_argument("--venue-id", help="enables efficient venue-wide note and rubric fetching")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseurl", default="https://api2.openreview.net")
    parser.add_argument("--limit", type=int, default=0, help="0 downloads every submission")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test and (not args.submission_invitation or not args.output):
        parser.error("--submission-invitation and --output are required")
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    self_test() if args.self_test else collect(args)
