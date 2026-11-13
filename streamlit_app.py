"""Review today's Anki batch from a phone.

This app NEVER schedules anything. It shows the cards export_due.py put in data/due.json,
records which button was pressed and how long the card took, and writes that list back to
the repo. import_reviews.py then replays those answers through Anki's own scheduler on the
desktop. Keeping the scheduling on one side of the wire is what makes it safe to review
here: the worst a bad session can do is record answers, never corrupt intervals.

Persistence works the same way the marathon dashboard's does, and for the same reason —
Streamlit Cloud's filesystem is ephemeral, so anything written locally is gone at the next
redeploy. Answers are committed to the private repo through the GitHub API, which needs a
GH_PAT secret with repo scope. Without one the app still works; you just have to use the
download button at the end and drop the file in yourself.
"""
import base64, json, os, time
import requests
import streamlit as st

REPO = "cavan-black/anki-phone"
HERE = os.path.dirname(os.path.abspath(__file__))
DUE = os.path.join(HERE, "data", "due.json")
MEDIA = os.path.join(HERE, "media")
SAVE_EVERY = 10          # answers between pushes; a crash costs at most this many
RATINGS = [("Again", 1), ("Hard", 2), ("Good", 3), ("Easy", 4)]

st.set_page_config(page_title="Anki", page_icon="🇯🇵", layout="centered",
                   initial_sidebar_state="collapsed")

STYLE = """
<style>
  #MainMenu, footer, header {visibility: hidden;}
  .block-container {padding-top: 2.2rem; padding-bottom: 1rem; max-width: 640px;}
  .word {font-size: clamp(2.6rem, 14vw, 4.2rem); line-height: 1.5; text-align: center;
         margin: 1.2rem 0 0.4rem;}
  .word ruby rt {font-size: 0.4em; opacity: 0.75;}
  .reading {font-size: 1.4rem; text-align: center; opacity: 0.85;}
  .meaning {font-size: 1.5rem; text-align: center; font-weight: 600; margin: 0.6rem 0 1.2rem;}
  .sent {font-size: 1.35rem; line-height: 2.1; text-align: center; margin-top: 0.8rem;}
  .sent ruby rt {font-size: 0.45em; opacity: 0.75;}
  .sent-en {font-size: 1rem; text-align: center; opacity: 0.7; margin-top: 0.3rem;}
  .meta {text-align: center; font-size: 0.78rem; opacity: 0.55; letter-spacing: 0.04em;}
  .stButton > button {height: 3.1rem; font-size: 1.05rem; font-weight: 600;}
  div[data-testid="stHorizontalBlock"] .stButton > button {height: 3.4rem;}
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)


@st.cache_data
def load_due():
    if not os.path.exists(DUE):
        return None
    with open(DUE, encoding="utf-8") as fh:
        return json.load(fh)


def audio_bytes(name):
    if not name:
        return None
    p = os.path.join(MEDIA, name)
    return open(p, "rb").read() if os.path.exists(p) else None


def push_answers(batch_id, answers):
    """Commit data/reviews.json to the private repo. Returns (ok, error)."""
    try:
        token = st.secrets.get("GH_PAT")
    except Exception:
        token = None          # no secrets.toml at all, e.g. running locally
    if not token:
        return False, "no GH_PAT secret"
    api = f"https://api.github.com/repos/{REPO}/contents/data/reviews.json"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    body = json.dumps({"batch_id": batch_id, "answers": answers}, indent=1)
    try:
        r = requests.get(api, headers=headers, timeout=15)
        sha = r.json().get("sha") if r.status_code == 200 else None
        payload = {"message": f"reviews: {len(answers)} answers ({batch_id})",
                   "content": base64.b64encode(body.encode()).decode(), "branch": "main"}
        if sha:
            payload["sha"] = sha
        r2 = requests.put(api, headers=headers, json=payload, timeout=20)
        if r2.status_code in (200, 201):
            return True, None
        return False, f"GitHub {r2.status_code}: {r2.text[:150]}"
    except Exception as exc:
        return False, str(exc)


def gate():
    """A Community Cloud app on a public repo is reachable by anyone with the URL, and
    this one carries a token that can write to the repo. So it asks for a PIN first.
    Set APP_PIN in the app's secrets; with no PIN set the app stays open, which is only
    sane while the repo is private."""
    try:
        pin = st.secrets.get("APP_PIN")
    except Exception:
        pin = None
    if not pin or st.session_state.get("unlocked"):
        return
    st.title("Anki")
    entered = st.text_input("PIN", type="password", label_visibility="collapsed",
                            placeholder="PIN")
    if entered:
        if entered == pin:
            st.session_state["unlocked"] = True
            st.rerun()
        else:
            st.error("Nope.")
    st.stop()


gate()

due = load_due()
if not due or not due.get("cards"):
    st.title("Nothing to review")
    st.write("Run `python export_due.py` on the laptop, then push.")
    st.stop()

cards = due["cards"]
ss = st.session_state
ss.setdefault("i", 0)
ss.setdefault("answers", [])
ss.setdefault("revealed", False)
ss.setdefault("shown_at", time.time())
ss.setdefault("saved_upto", 0)
ss.setdefault("save_err", None)


def save(force=False):
    n = len(ss.answers)
    if not force and n - ss.saved_upto < SAVE_EVERY:
        return
    ok, err = push_answers(due["batch_id"], ss.answers)
    ss.saved_upto = n if ok else ss.saved_upto
    ss.save_err = None if ok else err


def answer(rating):
    card = cards[ss.i]
    ss.answers.append({
        "card_id": card["card_id"],
        "rating": rating,
        "ms": int((time.time() - ss.shown_at) * 1000),
        "at": int(time.time()),
    })
    ss.i += 1
    ss.revealed = False
    ss.shown_at = time.time()
    save()


# ---- finished ----
if ss.i >= len(cards):
    save(force=True)
    st.title("Done")
    st.write(f"**{len(ss.answers)}** cards reviewed.")
    counts = {}
    for a in ss.answers:
        counts[a["rating"]] = counts.get(a["rating"], 0) + 1
    cols = st.columns(4)
    for col, (label, val) in zip(cols, RATINGS):
        col.metric(label, counts.get(val, 0))
    if ss.saved_upto == len(ss.answers):
        st.success("Saved to the repo. On the laptop: `git pull` then `python import_reviews.py`.")
    else:
        st.warning(f"Not saved automatically ({ss.save_err}). Download and drop this into "
                   f"`data/reviews.json` on the laptop instead.")
    st.download_button("Download reviews.json",
                       json.dumps({"batch_id": due["batch_id"], "answers": ss.answers}, indent=1),
                       file_name="reviews.json", mime="application/json")
    st.stop()

# ---- one card ----
card = cards[ss.i]
done, total = ss.i, len(cards)
st.progress(done / total)
saved_note = "" if ss.saved_upto >= done else f" · {done - ss.saved_upto} unsaved"
st.markdown(f'<div class="meta">{done} / {total}'
            f' · {card["deck"]}{saved_note}</div>', unsafe_allow_html=True)

# The front is the bare word. Furigana belongs on the back — putting it here would hand
# over the reading, which is most of what the card is asking for.
front = card["word_furigana"] if ss.revealed else card["word"]
st.markdown(f'<div class="word">{front}</div>', unsafe_allow_html=True)

if not ss.revealed:
    if st.button("Show answer", use_container_width=True, type="primary"):
        ss.revealed = True
        st.rerun()
else:
    wa = audio_bytes(card.get("word_audio"))
    if wa:
        st.audio(wa, format="audio/mp3", autoplay=True)
    if card["reading"]:
        st.markdown(f'<div class="reading">{card["reading"]}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="meaning">{card["meaning"]}</div>', unsafe_allow_html=True)
    if card["sentence"]:
        st.markdown(f'<div class="sent">{card["sentence_furigana"] or card["sentence"]}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="sent-en">{card["sentence_meaning"]}</div>',
                    unsafe_allow_html=True)
        sa = audio_bytes(card.get("sentence_audio"))
        if sa:
            st.audio(sa, format="audio/mp3")
    st.write("")
    for col, (label, val) in zip(st.columns(4), RATINGS):
        if col.button(label, use_container_width=True, key=f"r{val}_{ss.i}"):
            answer(val)
            st.rerun()

if ss.save_err:
    st.caption(f"⚠ last save failed: {ss.save_err}")
