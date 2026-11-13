# anki-phone

Review today's Anki batch from a phone, then apply the answers back through Anki's own
scheduler on the laptop. Nothing here schedules anything — that is deliberate.

## Daily loop

```
python export_due.py                 # writes data/due.json + copies any new audio
git add -A && git commit -m batch && git push
```

Review at the Streamlit URL on the phone. Answers push themselves back to this repo
every 10 cards and at the end.

```
git pull
.venv/Scripts/python import_reviews.py     # Anki must be CLOSED
```

Then open Anki and sync as normal.

## Why it is split this way

`export_due.py` reads the collection (on a copy, safe with Anki open) and only answers
"what is due". `import_reviews.py` replays the phone's button presses through
`build_answer`/`answer_card`, the same code the desktop uses. So intervals, ease and
lapses are always Anki's work. A bug in this repo can lose a session; it cannot produce
a wrong interval or damage the review log.

It backs the collection up to `backups/` before every import.

## Setup

- `python -m venv .venv && .venv/Scripts/python -m pip install anki` (import side)
- Deploy `streamlit_app.py` on Streamlit Community Cloud from this repo, private.
- Add a `GH_PAT` secret (repo scope) so the phone can push answers back. Without it the
  app still works — use the download button at the end and drop the file in by hand.

## Media

`media/` fills up as cards come due and is never pruned. Day one is ~15 MB; it converges
on the deck's full ~134 MB over a few weeks and then stops growing. Copying only the
current batch instead would rewrite ~15 MB of git objects every day.
