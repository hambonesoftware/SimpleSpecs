#!/usr/bin/env python3
"""CLI helper for dispatching per-section spec extraction jobs."""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.spec_extraction.jobs import enqueue_jobs_for_document, list_job_ids, run_job


async def _main(document_id: str, *, run: bool) -> None:
    sections, jobs = await enqueue_jobs_for_document(document_id)
    print(f"Enqueued document {document_id}: sections={sections} jobs={jobs}")
    if not run:
        return
    job_ids = list_job_ids(document_id, states={"queued"})
    if not job_ids:
        print("No queued jobs to run.")
        return
    print(f"Running {len(job_ids)} jobs synchronously…")
    for job_id in job_ids:
        await run_job(job_id)
    print("All queued jobs complete.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_id", help="Identifier returned by the header alignment API")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute queued jobs immediately after enqueuing",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    asyncio.run(_main(args.document_id, run=args.run))
