import os
import time
import json
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

import requests
import feedparser
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", "/data")
RSS_URL = os.getenv("RSS_URL", "https://habr.com/ru/rss/articles/?fl=ru")
PROMPT_PATH = os.getenv("PROMPT_PATH", "prompt.txt")

AMVERA_API_TOKEN = os.getenv("AMVERA_API_TOKEN")
AMVERA_ENDPOINT = os.getenv("AMVERA_ENDPOINT", "https://kong-proxy.yc.amvera.ru/api/v1/models/deepseek")

PAGE_SIZE = 6
MAX_STORE = int(os.getenv("MAX_STORE", "150"))
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "30"))

AI_WORKERS = int(os.getenv("AI_WORKERS", "4"))
LOCK_STALE_SECONDS = int(os.getenv("LOCK_STALE_SECONDS", "900"))

os.makedirs(DATA_DIR, exist_ok=True)
ARTICLES_FILE = os.path.join(DATA_DIR, "articles.json")
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")
GEN_LOCK_FILE = os.path.join(DATA_DIR, "generate.lock")

lock = Lock()
last_update_time = 0

progress_lock = Lock()
progress = {"done": 0, "total": 0}

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(BASE_DIR, "templates", "index.html")

STATIC_DIR = os.path.join(BASE_DIR, "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def s(x):
    if x is None:
        return ""
    return str(x).strip()


def to_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def clamp(v, min_v, max_v):
    if v < min_v:
        return min_v
    if v > max_v:
        return max_v
    return v


def read_file(path):
    try:
        return open(path, "r", encoding="utf-8").read()
    except Exception:
        return ""


def write_json(path, data):
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def read_articles():
    if not os.path.isfile(ARTICLES_FILE):
        return []
    try:
        raw = read_file(ARTICLES_FILE).strip()
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        result = []
        for it in data:
            if isinstance(it, dict):
                result.append(it)
        return result
    except Exception:
        return []


def entry_ts(entry):
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not t:
        return 0
    try:
        return int(time.mktime(t))
    except Exception:
        return 0


PROMPT_TEXT = read_file(PROMPT_PATH)
if not PROMPT_TEXT:
    PROMPT_TEXT = "{{TITLE}}"


def save_progress(done, total):
    with progress_lock:
        progress["done"] = int(done)
        progress["total"] = int(total)
        try:
            write_json(PROGRESS_FILE, {"done": progress["done"], "total": progress["total"]})
        except Exception:
            pass


def load_progress_from_file():
    try:
        if not os.path.isfile(PROGRESS_FILE):
            return {"done": 0, "total": 0}
        raw = read_file(PROGRESS_FILE).strip()
        if not raw:
            return {"done": 0, "total": 0}
        data = json.loads(raw)
        return {"done": to_int(data.get("done"), 0), "total": to_int(data.get("total"), 0)}
    except Exception:
        return {"done": 0, "total": 0}


def lock_is_stale(path):
    try:
        if not os.path.isfile(path):
            return False
        age = time.time() - os.path.getmtime(path)
        return age > LOCK_STALE_SECONDS
    except Exception:
        return False


def try_take_generate_lock():
    if lock_is_stale(GEN_LOCK_FILE):
        try:
            os.remove(GEN_LOCK_FILE)
        except Exception:
            pass

    try:
        fd = os.open(GEN_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        except Exception:
            pass
        return fd
    except FileExistsError:
        return None
    except Exception:
        return None


def release_generate_lock(fd):
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        if os.path.isfile(GEN_LOCK_FILE):
            os.remove(GEN_LOCK_FILE)
    except Exception:
        pass


def wait_for_generation_finish(max_wait_seconds=300):
    start = time.time()
    while True:
        if not os.path.isfile(GEN_LOCK_FILE):
            return True
        if time.time() - start > max_wait_seconds:
            return False
        time.sleep(0.3)


def call_ai(original_title):
    if not original_title:
        return original_title
    if not AMVERA_API_TOKEN:
        return original_title

    prompt = (PROMPT_TEXT or "{{TITLE}}").replace("{{TITLE}}", original_title)

    payload = {
        "model": "deepseek-V3",
        "messages": [{"role": "user", "text": prompt}],
    }

    headers = {
        "X-Auth-Token": "Bearer " + AMVERA_API_TOKEN,
        "Content-Type": "application/json",
    }

    r = requests.post(AMVERA_ENDPOINT, json=payload, headers=headers, timeout=40)
    r.raise_for_status()

    data = r.json() or {}
    choices = data.get("choices") or []
    if not choices:
        return original_title

    msg = (choices[0] or {}).get("message") or {}
    text = s(msg.get("content"))
    if not text:
        return original_title

    return text


def update_from_rss(rss_url):
    r = requests.get(rss_url, timeout=20, headers={"User-Agent": "honest-rss-api/1.0"})
    r.raise_for_status()

    parsed = feedparser.parse(r.text)
    entries = list(parsed.entries or [])

    old_items = read_articles()

    saved_by_link = {}
    saved_by_original = {}

    for it in old_items:
        link = s(it.get("link"))
        orig = s(it.get("original_title"))
        title = s(it.get("title"))

        if link:
            saved_by_link[link] = it

        if orig and title and title != orig:
            saved_by_original[orig] = title

    new_items = []
    count = 0

    for e in entries:
        if count >= MAX_STORE:
            break

        link = s(getattr(e, "link", None))
        orig_title = s(getattr(e, "title", None))
        if not link or not orig_title:
            continue

        tags = []
        tags_raw = getattr(e, "tags", None) or []
        for t in tags_raw:
            if isinstance(t, dict) and t.get("term"):
                tags.append({"term": t.get("term")})

        saved = saved_by_link.get(link) or {}
        saved_title = s(saved.get("title"))

        if (not saved_title) or (saved_title == orig_title):
            saved_title = saved_by_original.get(orig_title) or ""

        item = {
            "ts": entry_ts(e),
            "published": s(getattr(e, "published", None) or getattr(e, "updated", None)),
            "link": link,
            "author": s(getattr(e, "author", None) or getattr(e, "creator", None)),
            "summary": s(getattr(e, "summary", None) or getattr(e, "description", None)),
            "tags": tags,
            "original_title": orig_title,
            "title": saved_title or orig_title,
        }

        new_items.append(item)
        count += 1

    new_items.sort(key=lambda x: (to_int(x.get("ts")), s(x.get("title"))), reverse=True)
    write_json(ARTICLES_FILE, new_items[:MAX_STORE])


def need_generate(it):
    if not AMVERA_API_TOKEN:
        return False
    orig = s(it.get("original_title"))
    title = s(it.get("title"))
    if not orig:
        return False
    if (not title) or (title == orig):
        return True
    return False


def generate_titles_for_all(items):
    if not AMVERA_API_TOKEN:
        save_progress(0, 0)
        return

    ready_titles = {}
    for it in items:
        orig = s(it.get("original_title"))
        title = s(it.get("title"))
        if orig and title and title != orig:
            ready_titles[orig] = title

    to_do = []
    for i in range(len(items)):
        it = items[i]
        orig = s(it.get("original_title"))
        title = s(it.get("title"))

        if not orig:
            continue

        if orig in ready_titles:
            if title != ready_titles[orig]:
                it["title"] = ready_titles[orig]
            continue

        if (not title) or (title == orig):
            to_do.append(i)

    save_progress(0, len(to_do))

    if not to_do:
        return

    workers = AI_WORKERS
    if workers < 1:
        workers = 1
    if workers > 8:
        workers = 8

    jobs = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for idx in to_do:
            it = items[idx]
            orig = s(it.get("original_title"))

            if orig in ready_titles:
                jobs.append((idx, None, orig))
                continue

            future = ex.submit(call_ai, orig)
            jobs.append((idx, future, orig))

        done_now = 0
        for idx, future, orig in jobs:
            it = items[idx]

            if orig in ready_titles:
                it["title"] = ready_titles[orig]
            else:
                try:
                    new_title = future.result()
                except Exception:
                    new_title = orig

                new_title = s(new_title)
                if not new_title:
                    new_title = orig

                it["title"] = new_title

                if orig and new_title and new_title != orig:
                    ready_titles[orig] = new_title

            done_now += 1
            save_progress(done_now, len(to_do))

    save_progress(len(to_do), len(to_do))


@app.get("/api/getArticles")
def get_articles(offset: int = 0, limit: int = PAGE_SIZE, rss_url: str = RSS_URL):
    global last_update_time

    offset = clamp(to_int(offset, 0), 0, 10_000_000)
    limit = PAGE_SIZE

    with lock:
        if offset == 0:
            now = time.time()
            if now - last_update_time > REFRESH_SECONDS:
                update_from_rss(rss_url)
                last_update_time = now

        items = read_articles()
        items.sort(key=lambda x: (to_int(x.get("ts")), s(x.get("title"))), reverse=True)

    if offset == 0:
        need_any = False
        for it in items:
            if need_generate(it):
                need_any = True
                break

        if need_any:
            fd = try_take_generate_lock()
            if fd is None:
                wait_for_generation_finish(600)
            else:
                try:
                    generate_titles_for_all(items)
                    write_json(ARTICLES_FILE, items[:MAX_STORE])
                finally:
                    release_generate_lock(fd)
        else:
            save_progress(0, 0)

        items = read_articles()
        items.sort(key=lambda x: (to_int(x.get("ts")), s(x.get("title"))), reverse=True)

    part = items[offset:offset + limit]
    has_more = (offset + limit) < len(items)

    return {
        "count": len(part),
        "total": len(items),
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "items": part,
    }


@app.get("/api/progress")
def api_progress():
    data = load_progress_from_file()
    with progress_lock:
        progress["done"] = data.get("done", 0)
        progress["total"] = data.get("total", 0)
        return {"done": progress["done"], "total": progress["total"]}


@app.get("/")
def home():
    return FileResponse(INDEX_HTML)


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(INDEX_HTML)
