"""Apply the phone's answers to the real Anki collection.

Every interval, ease and lapse here is computed by Anki's own v3 scheduler through
build_answer/answer_card — the same code path the desktop uses when you press a key.
Nothing in this repo reimplements scheduling. A bug here can lose a session's answers;
it cannot invent a wrong interval or damage the review log.

HOW THE ORDERING WORKS. The v3 scheduler refuses to answer anything but the card at the
top of its own queue ("not at top of queue"), and its order is not the order the phone
showed cards in. So this walks the queue instead of the answer list: take the top card,
answer it if the phone graded it, otherwise bury it to bring the next one up. Every card
buried here is unburied again at the end, so burying is only ever a way to step past a
card — it is reversible and leaves no trace in the schedule.

Anki must be CLOSED: the collection takes an exclusive lock, and a running Anki holds
its own in-memory copy that would overwrite whatever is written underneath it.

Usage:  .venv/Scripts/python import_reviews.py [--dry-run]
"""
import argparse, json, os, shutil, sys, time
from collections import defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
COL_DIR = os.path.join(os.environ["APPDATA"], "Anki2", "User 1")
# ANKI_COLLECTION points the import at a copy — used to rehearse a batch end to end
# without touching the real collection.
COL = os.environ.get("ANKI_COLLECTION") or os.path.join(COL_DIR, "collection.anki2")
REVIEWS = os.path.join(HERE, "data", "reviews.json")
DUE = os.path.join(HERE, "data", "due.json")
BACKUPS = os.path.join(HERE, "backups")

# The app records Anki's familiar 1-4 ease (and that is what lands in the revlog), but
# CardAnswer.Rating is zero-based: AGAIN 0, HARD 1, GOOD 2, EASY 3.
RATING_OFFSET = 1
# A card that cannot be buried out of the way would otherwise spin the loop forever.
MAX_STEPS = 20000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be applied, touch nothing")
    args = ap.parse_args()

    if not os.path.exists(REVIEWS):
        sys.exit("no data/reviews.json — pull from the repo first")
    payload = json.load(open(REVIEWS, encoding="utf-8"))
    answers = payload.get("answers") or []
    if not answers:
        print("nothing to apply")
        return

    if os.path.exists(DUE):
        due_batch = json.load(open(DUE, encoding="utf-8")).get("batch_id")
        if due_batch != payload.get("batch_id"):
            sys.exit(f"batch mismatch: reviews are for {payload.get('batch_id')}, "
                     f"due.json holds {due_batch}. Pull the matching pair first.")

    bad = [a for a in answers if a.get("rating") not in (1, 2, 3, 4)]
    if bad:
        sys.exit(f"{len(bad)} answers have a rating outside 1-4 — refusing to import")

    print(f"batch {payload.get('batch_id')}: {len(answers)} answers")
    if args.dry_run:
        for a in answers[:5]:
            print("  ", a)
        if len(answers) > 5:
            print("   ...")
        return

    os.makedirs(BACKUPS, exist_ok=True)
    backup = os.path.join(BACKUPS, f"collection-{time.strftime('%Y%m%d-%H%M%S')}.anki2")
    shutil.copy2(COL, backup)
    print(f"backup -> {backup}")

    import anki.collection  # noqa: F401  (import order matters; see anki.scheduler)
    from anki.collection import Collection

    try:
        col = Collection(COL)
    except Exception as exc:
        sys.exit(f"could not open the collection ({exc}).\nClose Anki and try again.")

    pending = defaultdict(deque)
    for a in answers:
        pending[a["card_id"]].append(a)

    applied, buried, steps = 0, [], 0
    last_buried = None
    started = time.time()
    try:
        while any(pending.values()) and steps < MAX_STEPS:
            steps += 1
            queued = col.sched.get_queued_cards(fetch_limit=1)
            if not queued.cards:
                print("queue emptied before every answer was applied")
                break
            top = queued.cards[0]
            cid = top.card.id
            if pending[cid]:
                a = pending[cid].popleft()
                card = col.get_card(cid)
                # Hand Anki the time the phone actually measured, so the revlog keeps a
                # truthful answer time rather than one invented at import.
                card.timer_started = time.time() - max(a.get("ms", 0), 0) / 1000.0
                col.sched.answer_card(col.sched.build_answer(
                    card=card, states=top.states, rating=a["rating"] - RATING_OFFSET))
                applied += 1
            else:
                if cid == last_buried:
                    print(f"card {cid} will not leave the top of the queue — stopping")
                    break
                col.sched.bury_cards([cid], manual=False)
                buried.append(cid)
                last_buried = cid
        if buried:
            col.sched.unbury_cards(buried)
    finally:
        col.close()

    left = sum(len(v) for v in pending.values())
    print(f"applied {applied} / {len(answers)} in {time.time() - started:.1f}s "
          f"({len(buried)} cards stepped past and restored)")
    if left:
        print(f"WARNING: {left} answers could not be applied — their cards were no longer "
              f"in today's queue (answered on the desktop already, or suspended since "
              f"export). They have been dropped.")

    payload["answers"] = []
    payload["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    payload["applied_count"] = applied
    payload["dropped_count"] = left
    with open(REVIEWS, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    print("cleared data/reviews.json — commit it, then open Anki and sync.")


if __name__ == "__main__":
    main()
