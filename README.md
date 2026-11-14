# anki-phone

Review today's Anki batch from a phone, then apply the answers back through Anki's own
scheduler on the laptop. Nothing here schedules anything — that is deliberate.

## Daily loop

```
python export_due.py                 # writes data/due.json
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
- Deploy `streamlit_app.py` on Streamlit Community Cloud from this repo.
- Add a `GH_PAT` secret (repo scope) so the phone can push answers back. Without it the
  app still works — use the download button at the end and drop the file in by hand.

## Grading

Two buttons, the way Migaku does it: you either got it or you didn't. They emit Anki's
ease 1 (Again) and 3 (Good), so the import replays them through the real scheduler
unchanged — Hard and Easy are never sent from the phone. One consequence worth knowing:
a card you find trivial gets a Good-sized interval rather than a long one, so easy cards
come back sooner than they would on the desktop. Use the desktop for the full scale.

## No audio

This used to copy the deck's mp3s into `media/` so the phone could play them. The repo
has to be public (see below) and Kaishi 1.5k ships with no licence at all — its audio is
partly from the AJT Japanese add-on, partly from assorted Core decks — so publishing 575
of those files was a redistribution nobody granted. The card is text only. The local
`media/` copy is kept but gitignored.

## Public repo

Streamlit Community Cloud allows one private app per account, which is already spoken
for, so this repo is public and the app is reachable by anyone who has the URL. The app
holds a GitHub token that can write here, so set an `APP_PIN` secret alongside `GH_PAT`
and the app asks for it before showing anything. With no `APP_PIN` set the app is open.

What is public, and worth knowing: a day's slice of card text in `data/due.json`, and
your review timings. No audio, and no credentials — those live only in Streamlit's
secrets store.
