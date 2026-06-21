import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WIKI_CACHE = ROOT / "wiki_cache"
WIKI_CACHE.mkdir(parents=True, exist_ok=True)


def parse_wiki_query(text):
    text = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    patterns = [
        r"^(?:кто\s+такой|кто\s+такая)\s+(.+)$",
        r"^(?:что\s+такое|что\s+это\s+такое|что\s+это)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            query = match.group(1).strip(" ?!.,")
            if len(query) >= 2:
                return query
    return ""


def find_wikipedia(query):
    query = re.sub(r"\s+", " ", query or "").strip()
    if not query:
        return None
    summary = _summary(query)
    if not _usable(summary):
        title = _search_title(query)
        summary = _summary(title) if title else None
    if not _usable(summary):
        return None
    title = summary.get("title", query)
    extract = re.sub(r"\s+", " ", summary.get("extract", "")).strip()
    description = re.sub(r"\s+", " ", summary.get("description", "")).strip()
    image_path = _download_image(summary.get("thumbnail", {}).get("source"), title)
    return {
        "query": query,
        "title": title,
        "description": description,
        "extract": _shorten(extract),
        "url": summary.get("content_urls", {}).get("desktop", {}).get("page", ""),
        "image_path": str(image_path) if image_path else "",
    }


def _summary(title):
    if not title:
        return None
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    request = urllib.request.Request(url, headers={"User-Agent": "JarvisPython/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _search_title(query):
    params = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": 1,
        "srlimit": 1,
    })
    request = urllib.request.Request(
        f"https://ru.wikipedia.org/w/api.php?{params}",
        headers={"User-Agent": "JarvisPython/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results = payload.get("query", {}).get("search", [])
        return results[0].get("title") if results else ""
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError):
        return ""


def _usable(summary):
    if not isinstance(summary, dict):
        return False
    if summary.get("type") == "disambiguation":
        return False
    extract = summary.get("extract", "")
    return bool(summary.get("title") and extract and len(extract) > 30)


def _shorten(text, limit=720):
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(". ", 1)[0].strip()
    return (cut or text[:limit].strip()).rstrip(".") + "."


def _download_image(url, title):
    if not url:
        return None
    safe = re.sub(r"[^a-zA-Zа-яА-Я0-9_.-]+", "_", title).strip("_")[:70] or "wiki"
    ext = ".jpg"
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg" if suffix == ".jpeg" else suffix
    path = WIKI_CACHE / f"{safe}{ext}"
    if path.exists() and path.stat().st_size > 0:
        return path
    request = urllib.request.Request(url, headers={"User-Agent": "JarvisPython/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = response.read()
        if data:
            path.write_bytes(data)
            return path
    except (OSError, urllib.error.URLError):
        return None
    return None
