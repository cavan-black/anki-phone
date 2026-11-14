"""Pull today's due cards out of the Anki collection into data/due.json.

Read-only against the collection: it works on a copy, so it is safe to run with Anki
open. Nothing here computes a schedule. Which cards are due is read straight from the
queues, and what answering them does to the schedule is decided later, by Anki itself,
in import_reviews.py. That split is the whole safety story — the phone never guesses an
interval, so a bad batch can never corrupt 17k reviews of history.

NO AUDIO, deliberately. This used to copy the deck's mp3s into media/ so the phone
could play them. The repo has to be public — Community Cloud's free tier allows one
private app and the marathon dashboard holds it — and Kaishi 1.5k ships with no licence
at all, its audio partly from the AJT Japanese add-on and partly from assorted Core
decks. Publishing 575 of those files was a redistribution nobody granted. Card text
still goes out in due.json, which is the same question at a far smaller scale: one
day's slice of a deck you already own is a defensible line, 16 MB of someone else's
audio on a public URL is not.

Usage:  python export_due.py [--new N]
"""
import argparse, json, os, re, shutil, sqlite3, time, uuid

COL_DIR = os.path.join(os.environ["APPDATA"], "Anki2", "User 1")
COL = os.path.join(COL_DIR, "collection.anki2")

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, ".export.anki2")
DATA = os.path.join(HERE, "data")

SOUND = re.compile(r"\[sound:(.*?)\]")
TAG = re.compile(r"<[^>]+>")
# Anki writes furigana as 漢字[かんじ]; a reading is attached to the run of characters
# before it, delimited by a space or the start of the field.
RUBY = re.compile(r"([^ >]+?)\[(.+?)\]")


def furigana_html(s):
    return RUBY.sub(r"<ruby>\1<rt>\2</rt></ruby>", SOUND.sub("", s or "")).strip()


def plain(s):
    return TAG.sub("", SOUND.sub("", s or "")).replace("\xa0", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", type=int, default=10,
                    help="how many new cards to include (default 10)")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    shutil.copy2(COL, WORK)
    db = sqlite3.connect(WORK)

    crt = db.execute("select crt from col").fetchone()[0]
    today = int((time.time() - crt) // 86400)
    now_s = int(time.time())

    field_names = {}
    for ntid, ord_, name in db.execute("select ntid,ord,name from fields order by ntid,ord"):
        field_names.setdefault(ntid, []).append(name)

    learning, review, new = [], [], []
    for row in db.execute("""
            select c.id, c.queue, c.due, c.ivl, c.reps, c.lapses, n.mid, n.flds, d.name
              from cards c join notes n on n.id = c.nid join decks d on d.id = c.did
             where c.queue in (0,1,2,3)"""):
        cid, queue, due, ivl, reps, lapses, mid, flds, deck = row
        f = dict(zip(field_names.get(mid, []), flds.split("\x1f")))
        card = {
            "card_id": cid, "deck": deck, "ivl": ivl, "reps": reps, "lapses": lapses,
            "word": plain(f.get("Word")),
            "word_furigana": furigana_html(f.get("Word Furigana")),
            "reading": plain(f.get("Word Reading")),
            "meaning": plain(f.get("Word Meaning")),
            "sentence": plain(f.get("Sentence")),
            "sentence_furigana": furigana_html(f.get("Sentence Furigana")),
            "sentence_meaning": plain(f.get("Sentence Meaning")),
            "pitch": f.get("Pitch Accent", ""),
        }
        if queue == 1 and due <= now_s:
            learning.append(card)
        elif queue in (2, 3) and due <= today:
            review.append(card)
        elif queue == 0:
            new.append(card)

    new.sort(key=lambda c: c["card_id"])
    batch = learning + review + new[:args.new]

    out = {
        "batch_id": uuid.uuid4().hex[:12],
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "collection_day": today,
        "counts": {"learning": len(learning), "review": len(review),
                   "new_available": len(new), "new_included": min(args.new, len(new))},
        "cards": batch,
    }
    with open(os.path.join(DATA, "due.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    # A fresh batch invalidates any answers still sitting unapplied; importing them
    # after a re-export would replay reviews against a schedule that has moved on.
    rv = os.path.join(DATA, "reviews.json")
    if os.path.exists(rv):
        old = json.load(open(rv, encoding="utf-8"))
        if old.get("batch_id") != out["batch_id"] and old.get("answers"):
            print(f"WARNING: {len(old['answers'])} unapplied answers from batch "
                  f"{old.get('batch_id')} — run import_reviews.py before exporting again.")
    with open(rv, "w", encoding="utf-8") as fh:
        json.dump({"batch_id": out["batch_id"], "answers": []}, fh, indent=1)

    db.close()
    os.remove(WORK)
    print(json.dumps(out["counts"], indent=1))
    print(f"batch {out['batch_id']}: {len(batch)} cards")


if __name__ == "__main__":
    main()
