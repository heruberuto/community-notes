"""Daily cron job: download every Community Notes snapshot still on the CDN that
is not yet (completely) in the local archive.

    python sync_snapshots.py            # sync
    python sync_snapshots.py --check    # only report what would be downloaded

A local snapshot counts as complete when its manifest.json exists (cn_downloader
writes it only after every file was downloaded and zip-verified), every dataset
in it has at least one part, every listed file exists with the recorded size,
and no *.part leftovers remain. Anything else is re-downloaded; cn_downloader
skips finished files and resumes .part files, so a retry only fetches what's
missing.

Exit code is non-zero if any snapshot failed, so cron can mail on failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import sys
import traceback
from pathlib import Path

if not sys.stdout.isatty():
    os.environ.setdefault("TQDM_DISABLE", "1")  # no progress bars in cron logs

from cn_downloader import (  # noqa: E402
    DATASETS,
    DEFAULT_OUT_DIR,
    download_snapshot,
    list_available_snapshots,
    make_session,
)


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def incomplete_reason(snapshot_dir: Path) -> str | None:
    """None if the local snapshot is complete, else a short reason why not."""
    if not snapshot_dir.exists():
        return "missing"
    if any(snapshot_dir.rglob("*.part")):
        return "interrupted download (.part files)"
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        return "no manifest.json"
    files = json.loads(manifest_path.read_text()).get("files", {})
    for dataset in DATASETS:
        if not files.get(dataset):
            return f"dataset {dataset} missing from manifest"
        for f in files[dataset]:
            path = Path(f["path"])
            if not path.exists():
                return f"{path.name} missing"
            if path.stat().st_size != f["bytes"]:
                return f"{path.name} has wrong size"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--check", action="store_true",
                        help="only report missing/incomplete snapshots, download nothing")
    args = parser.parse_args()

    # A day's sync can take hours; never let two runs write the same files.
    args.out.mkdir(parents=True, exist_ok=True)
    lock = open(args.out / ".sync.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another sync is still running, exiting")
        return 0

    available = list_available_snapshots(make_session())
    log(f"on CDN: {', '.join(f'{d:%m-%d}' for d in available) or 'nothing'}")

    todo = []
    for date in available:
        reason = incomplete_reason(args.out / f"{date:%Y-%m-%d}")
        if reason:
            todo.append(date)
            log(f"  {date:%Y-%m-%d}: {reason}")
    log(f"{len(available) - len(todo)}/{len(available)} complete, {len(todo)} to download")

    if args.check:
        return 0

    failed = []
    for date in todo:
        try:
            download_snapshot(date, out_dir=args.out)
            reason = incomplete_reason(args.out / f"{date:%Y-%m-%d}")
            if reason:  # e.g. CDN was still uploading that day's parts
                raise RuntimeError(f"still incomplete after download: {reason}")
            log(f"  {date:%Y-%m-%d}: done")
        except Exception:
            failed.append(date)
            log(f"  {date:%Y-%m-%d}: FAILED")
            traceback.print_exc()

    if failed:
        log(f"failed: {', '.join(f'{d:%Y-%m-%d}' for d in failed)} (retried next run)")
        return 1
    log("all available snapshots are archived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
