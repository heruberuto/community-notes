# community-notes

Tools for downloading and analyzing the **X (Twitter) Community Notes public data dump**.

## How the data can be obtained

| route | auth | notes |
| --- | --- | --- |
| [Download Data page](https://x.com/i/communitynotes/download-data) | X login required | official UI; links to the same daily files |
| **Direct CDN URLs** (what this repo uses) | none | `https://ton.twimg.com/birdwatch-public-data/YYYY/MM/DD/<dataset>/<stem>-<NNNNN>.zip` |
| [AI Note Writer API](https://docs.x.com/x-api/community-notes/) | API key | for *writing* notes / fetching eligible posts, not for bulk dumps |

Each zip contains a single TSV (header row, tab-separated). Datasets and their CDN paths
(sizes as of the 2026-08-25 snapshot, zipped):

- `notes/notes-0000N.zip` — all surviving notes incl. full text (3 parts, ~0.5 GB)
- `noteRatings/ratings-0000N.zip` — all ratings (multiple parts, several GB — the bulk of the dump)
- `noteStatusHistory/noteStatusHistory-00000.zip` — status timeline of every scored note (~0.18 GB)
- `userEnrollment/userEnrollment-00000.zip` — anonymized contributor enrollment (~0.07 GB)
- a fifth dataset, **Note Requests**, is documented but its direct CDN path is not publicly known —
  grab it from the logged-in Download Data page if needed

Snapshots are published **daily (best effort)** and are **cumulative** since the January 2021
launch, with a 48-hour lag. Deleted notes are removed from all subsequent dumps
(`noteStatusHistory` retains their metadata: noteId, timestamps, status history — not the text).
Column-by-column schema: [official docs](https://communitynotes.x.com/guide/en/under-the-hood/download-data)
([markdown source](https://github.com/twitter/communitynotes/blob/main/documentation/under-the-hood/download-data.md)).

## ⚠️ Past snapshots

**Past daily snapshots ARE downloadable, but only for a rolling window of ~7 days** — just put a
past date in the URL. Verified empirically on 2026-08-25: `2026/08/19`–`2026/08/25` respond,
`2026/08/18` and older return 404. X provides no official long-term snapshot archive.

For history beyond the window:

- **Zenodo, CC-BY-4.0** — *From Birdwatch to Community Notes* dataset, **2021-01-23 → 2025-01-23**
  (monthly rating files, notes with language annotation, interaction graphs):
  [zenodo.org/records/16761304](https://zenodo.org/records/16761304)
- Early Birdwatch-era automated scrapes: [shiruken/birdwatch-data](https://github.com/shiruken/birdwatch-data)
- **Roll your own**: run `cn_downloader.py` from a daily cron job — the only reliable way to
  capture note-status evolution and note texts before deletion.

## License of the data

There is **no explicit open-data license**. X states the contributions are *"publicly available so
that anyone has free access to analyze the data"*; use is governed by the
[X Terms of Service](https://x.com/en/tos). Participant IDs are hashed/anonymized and the dump
contains no PII. The Apache-2.0 license on [twitter/communitynotes](https://github.com/twitter/communitynotes)
covers the *scoring source code only*, not the data. (The Zenodo historical archive above is
CC-BY-4.0.) Community Notes data is routinely used in peer-reviewed research.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m ipykernel install --user --name community-notes --display-name "Python (community-notes)"

jupyter lab download_community_notes.ipynb   # interactive
# or headless:
python cn_downloader.py                      # latest snapshot, all datasets -> data/raw/YYYY-MM-DD/
python cn_downloader.py --list               # which snapshot dates are still on the CDN
python cn_downloader.py --date 2026-08-19 --datasets notes,noteStatusHistory
```

Downloads are resumable (complete files are skipped), zip-integrity-checked, and summarized in a
`manifest.json` per snapshot. `pandas` reads the zips directly:
`pd.read_csv("data/raw/2026-08-25/notes/notes-00000.zip", sep="\t", dtype=str)`.
