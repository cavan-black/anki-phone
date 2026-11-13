"""Pull today's due cards out of the Anki collection into data/due.json, and copy any
audio they need into media/.

Read-only against the collection: it works on a copy, so it is safe to run with Anki
open. Nothing here computes a schedule. Which cards are due is read straight from the
queues, and what answering them does to the schedule is decided later, by Anki itself,
in import_reviews.py. That split is the whole safety story — the phone never guesses an
interval, so a bad batch can never corrupt 17k reviews of history.

Media is copied once and never deleted. Day one costs ~15 MB; after a few weeks the
repo holds most of the deck's audio and new exports copy almost nothing. The
alternative — shipping only the current batch and clearing the rest — would rewrite
~15 MB of git objects every single day.

Usage:  python export_due.py [--new N]
"""
import argparse, json, os, re, shutil, sqlite3, time, uuid

COL_DIR = os.path.join(os.environ["APPDATA"], "Anki2", "User 1")
COL = os.path.join(COL_DIR, "collection.anki2")
MEDIA_SRC = os.path.join(COL_DIR, "collection.media")

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, ".export.anki2")
DATA = os.path.join(HERE, "data")
MEDIA_DST = os.path.join(HERE, "media")

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
    os.makedirs(MEDIA_DST, exist_ok=True)
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
            "word_audio": (SOUND.findall(f.get("Word Audio") or "") or [None])[0],
            "sentence_audio": (SOUND.findall(f.get("Sentence Audio") or "") or [None])[0],
        }
        if queue == 1 and due <= now_s:
            learning.append(card)
        elif queue in (2, 3) and due <= today:
            review.append(card)
        elif queue == 0:
            new.append(card)

    new.sort(key=lambda c: c["card_id"])
    batch = learning + review + new[:args.new]

    copied = 0
    for card in batch:
        for key in ("word_audio", "sentence_audio"):
            name = card.get(key)
            if not name:
                continue
            dst = os.path.join(MEDIA_DST, name)
            if not os.path.exists(dst):
                src = os.path.join(MEDIA_SRC, name)
                if os.path.exists(src):
                    shutil.copy2(src, dst)
                    copied += 1
                else:
                    card[key] = None

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
    print(f"batch {out['batch_id']}: {len(batch)} cards, {copied} new audio files copied")


if __name__ == "__main__":
    main()
