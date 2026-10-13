import time
import urllib.request

UA = {"User-Agent": "bbm-sentinel-jember/0.1 (+research; contact via repo)"}


def get_text(url, timeout=25, retries=3, backoff=2.0):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # collectors must fail soft, never kill a run
            last = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last


def get_json(url, **kwargs):
    import json

    return json.loads(get_text(url, **kwargs))
