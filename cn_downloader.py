"""Downloader for the X (Twitter) Community Notes public data dump.

The dump lives at unauthenticated, date-stamped URLs:

    https://ton.twimg.com/birdwatch-public-data/YYYY/MM/DD/<dataset>/<stem>-<NNNNN>.zip

Each zip contains a single TSV (tab-separated, header row). Datasets are
cumulative: every daily snapshot contains all surviving notes/ratings since
the program started in January 2021 (deleted notes vanish from later
snapshots; noteStatusHistory keeps their metadata). Only a rolling window of
roughly the last 7 daily snapshots stays on the CDN — older dates return 404.

Usage (CLI):
    python cn_downloader.py                     # latest snapshot, all datasets
    python cn_downloader.py --date 2026-08-24   # a specific (recent) snapshot
    python cn_downloader.py --datasets notes,userEnrollment
    python cn_downloader.py --list              # probe which snapshot dates exist
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import zipfile
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from tqdm.auto import tqdm
from urllib3.util.retry import Retry

BASE_URL = "https://ton.twimg.com/birdwatch-public-data"

# dataset directory on the CDN -> file stem inside it
DATASETS = {
    "notes": "notes",
    "noteRatings": "ratings",
    "noteStatusHistory": "noteStatusHistory",
    "userEnrollment": "userEnrollment",
}

# The CDN keeps roughly the last 7 daily snapshots (verified 2026-08-25:
# 2026-08-19..25 respond, 2026-08-18 is already gone).
SNAPSHOT_WINDOW_DAYS = 10  # probe a little past 7 to be safe

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "data" / "raw"

CHUNK_SIZE = 1 << 20  # 1 MiB
POLITE_DELAY_S = 1.0  # pause between files; the CDN throttles rapid-fire requests


def make_session() -> requests.Session:
    """Session with aggressive retries — ton.twimg.com drops connections when hit too fast."""
    session = requests.Session()
    retry = Retry(
        total=8,
        connect=8,
        read=8,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = "community-notes-downloader (academic research)"
    return session


def snapshot_url(date: dt.date, dataset: str, part: int) -> str:
    stem = DATASETS[dataset]
    return f"{BASE_URL}/{date:%Y/%m/%d}/{dataset}/{stem}-{part:05d}.zip"


def remote_size(session: requests.Session, url: str) -> int | None:
    """Size in bytes of a remote file, or None if it does not exist (404).

    Uses a 1-byte ranged GET: the CDN answers plain HEAD requests with 404
    even for files that exist.
    """
    resp = session.get(url, headers={"Range": "bytes=0-0"}, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    content_range = resp.headers.get("Content-Range", "")  # "bytes 0-0/12345"
    if "/" in content_range:
        return int(content_range.rsplit("/", 1)[1])
    return None


def snapshot_exists(date: dt.date, session: requests.Session | None = None) -> bool:
    session = session or make_session()
    return remote_size(session, snapshot_url(date, "notes", 0)) is not None


def find_latest_snapshot(session: requests.Session | None = None) -> dt.date | None:
    """Most recent date whose snapshot is on the CDN (today, else walk back)."""
    session = session or make_session()
    today = dt.date.today()
    for back in range(SNAPSHOT_WINDOW_DAYS):
        date = today - dt.timedelta(days=back)
        if snapshot_exists(date, session):
            return date
        time.sleep(POLITE_DELAY_S)
    return None


def list_available_snapshots(session: requests.Session | None = None) -> list[dt.date]:
    """All snapshot dates still on the CDN (the rolling ~7-day window)."""
    session = session or make_session()
    available = []
    today = dt.date.today()
    for back in range(SNAPSHOT_WINDOW_DAYS):
        date = today - dt.timedelta(days=back)
        if snapshot_exists(date, session):
            available.append(date)
        time.sleep(POLITE_DELAY_S)
    return sorted(available)


def download_file(
    session: requests.Session,
    url: str,
    dest: Path,
    expected_size: int,
    max_attempts: int = 10,
) -> Path:
    """Stream one file to dest; skip if already complete; verify the zip.

    The CDN resets long-lived connections mid-transfer, so interrupted
    downloads are resumed from the current .part size via HTTP Range.
    """
    if dest.exists() and dest.stat().st_size == expected_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    attempt = 0
    while True:
        offset = tmp.stat().st_size if tmp.exists() else 0
        if offset > expected_size:  # stale leftover from an older snapshot
            tmp.unlink()
            offset = 0
        if offset == expected_size:
            break
        try:
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            with session.get(url, stream=True, timeout=(30, 120), headers=headers) as resp:
                resp.raise_for_status()
                if offset and resp.status_code != 206:  # server ignored the Range
                    offset = 0
                with open(tmp, "ab" if offset else "wb") as fh, tqdm(
                    total=expected_size,
                    initial=offset,
                    unit="B",
                    unit_scale=True,
                    desc=dest.name,
                    leave=False,
                ) as bar:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        fh.write(chunk)
                        bar.update(len(chunk))
            if tmp.stat().st_size == expected_size:
                break
            raise IOError(f"short read: {tmp.stat().st_size}/{expected_size} bytes")
        except (requests.RequestException, IOError) as exc:
            attempt += 1
            if attempt >= max_attempts:
                raise
            wait = min(2**attempt, 60)
            print(f"    {dest.name}: {exc} — retry {attempt}/{max_attempts} in {wait}s")
            time.sleep(wait)
    if zipfile.ZipFile(tmp).testzip() is not None:
        raise IOError(f"{dest.name}: zip integrity check failed")
    tmp.rename(dest)
    return dest


def download_dataset(
    date: dt.date,
    dataset: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    session: requests.Session | None = None,
) -> list[Path]:
    """Download every part (…-00000.zip, -00001.zip, …) of one dataset."""
    session = session or make_session()
    dataset_dir = Path(out_dir) / f"{date:%Y-%m-%d}" / dataset
    paths = []
    part = 0
    while True:
        url = snapshot_url(date, dataset, part)
        size = remote_size(session, url)
        if size is None:  # explicit 404 — no more parts
            break
        dest = dataset_dir / url.rsplit("/", 1)[1]
        print(f"  {dataset} part {part}: {size / 1e6:,.1f} MB")
        download_file(session, url, dest, size)
        paths.append(dest)
        part += 1
        time.sleep(POLITE_DELAY_S)
    return paths


def download_snapshot(
    date: dt.date | None = None,
    datasets: list[str] | None = None,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict:
    """Download a full daily snapshot. Returns a manifest dict (also written to disk)."""
    session = make_session()
    if date is None:
        date = find_latest_snapshot(session)
        if date is None:
            raise RuntimeError(
                "No snapshot found in the last "
                f"{SNAPSHOT_WINDOW_DAYS} days — has the URL scheme changed?"
            )
    datasets = datasets or list(DATASETS)
    unknown = set(datasets) - set(DATASETS)
    if unknown:
        raise ValueError(f"Unknown datasets: {sorted(unknown)}; valid: {list(DATASETS)}")

    print(f"Downloading Community Notes snapshot {date:%Y-%m-%d} -> {out_dir}")
    manifest = {"snapshot_date": f"{date:%Y-%m-%d}", "base_url": BASE_URL, "files": {}}
    for dataset in datasets:
        print(f"[{dataset}]")
        paths = download_dataset(date, dataset, out_dir, session)
        manifest["files"][dataset] = [
            {"path": str(p), "bytes": p.stat().st_size} for p in paths
        ]
    manifest_path = Path(out_dir) / f"{date:%Y-%m-%d}" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    total_gb = sum(f["bytes"] for fs in manifest["files"].values() for f in fs) / 1e9
    print(f"Done: {total_gb:.2f} GB (zipped) in {manifest_path.parent}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=dt.date.fromisoformat, default=None,
                        help="snapshot date YYYY-MM-DD (default: latest available)")
    parser.add_argument("--datasets", default=None,
                        help=f"comma-separated subset of {list(DATASETS)}")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--list", action="store_true",
                        help="only list snapshot dates still on the CDN, then exit")
    args = parser.parse_args()

    if args.list:
        dates = list_available_snapshots()
        print("Snapshots currently on the CDN:")
        for d in dates:
            print(f"  {d:%Y-%m-%d}")
        return

    datasets = args.datasets.split(",") if args.datasets else None
    download_snapshot(args.date, datasets, args.out)


if __name__ == "__main__":
    main()
