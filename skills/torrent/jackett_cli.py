#!/usr/bin/env python
"""Minimal CLI for a local Jackett server (stdlib + parsett).

  python jackett_cli.py list [--configured] [--public] [--lang en] [--grep x]
  python jackett_cli.py add 1337x [--set key=value ...]
  python jackett_cli.py remove 1337x
  python jackett_cli.py test 1337x
  python jackett_cli.py search "ubuntu 24.04" [-i 1337x,yts] [-c 2000] [-q 1080p+] [--clean [--lang ja]]
      [--title "Your Name" --title "Kimi no Na wa"] [--words] [--magnet] [-n 20] [--json]
  python jackett_cli.py show tt0903747 [-q 1080p+] [--clean] [-n 2]   # TV: season + complete packs
"""
import argparse, hashlib, http.cookiejar, json, os, re, socket, subprocess, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from PTT import parse_title  # pip install parsett

HERE = os.path.dirname(os.path.abspath(__file__))
_CFG_FILE = os.path.join(HERE, "config.json")  # written by install.py
CFG = json.load(open(_CFG_FILE, encoding="utf-8")) if os.path.exists(_CFG_FILE) else {}


def _exe(folder, *names):
    """First existing executable among names in folder; None if the folder is unset or holds none of them."""
    return next((p for n in names if folder and os.path.isfile(p := os.path.join(folder, n))), None)


SERVICES = [  # (port, exe, env): started hidden on demand, so the user never launches anything by hand
    (9117, _exe(os.environ.get("JACKETT_DIR") or CFG.get("jackett_dir"), "JackettConsole.exe", "jackett"), {}),
    (8191, _exe(os.environ.get("FLARESOLVERR_DIR") or CFG.get("flaresolverr_dir"), "flaresolverr.exe", "flaresolverr"),
     {"HOST": "127.0.0.1", "PORT": "8191"}),
]
URL = os.environ.get("JACKETT_URL", "http://127.0.0.1:9117").rstrip("/")
CONFIG = os.environ.get("JACKETT_CONFIG") or next(  # Jackett's data folder: Windows default, then Linux/macOS
    (p for p in (r"C:\ProgramData\Jackett\ServerConfig.json", os.path.expanduser("~/.config/Jackett/ServerConfig.json"))
     if os.path.exists(p)), r"C:\ProgramData\Jackett\ServerConfig.json")

# Release titles are parsed with PTT (the parser lineage Torrentio uses); ranking follows TRaSH-style tiers.
RES = {"1080p+": {"1080p", "1440p", "2160p"}, "4k": {"2160p"}, "2160p": {"2160p"}, "uhd": {"2160p"}}
RES_RANK = {"2160p": 3, "1440p": 2, "1080p": 1}
SRC_RANK = {"bluray remux": 4, "remux": 4, "bluray": 3, "web-dl": 2, "web": 2, "webrip": 1, "bdrip": 1, "brrip": 1}
AUDIO_RANK = {"TrueHD": 3, "DTS Lossless": 3, "FLAC": 3, "PCM": 3, "Dolby Digital Plus": 2, "DTS Lossy": 2,
              "Dolby Digital": 1}
MIN_SEEDS = 5  # below this a swarm may never finish; such rows sink below every healthy one


def rank(r):
    """Healthy swarm > resolution > source > DV/HDR > audio codec tier > Atmos > channels > seeders.
    ponytail: title tags only; on non-English discs the Atmos/lossless track may belong to the dub."""
    p, audio = r["_p"], r["_p"].get("audio") or []
    hdr = p.get("hdr") or []
    src = SRC_RANK.get((p.get("quality") or "").lower(), 0)
    codec = max([AUDIO_RANK.get(a, 0) for a in audio] + [3 if src == 4 else 0])  # a remux keeps the disc's lossless track
    ch = p.get("channels") or []
    return (r["Seeders"] >= MIN_SEEDS, RES_RANK.get(p.get("resolution"), 0), src,
            2 if "DV" in hdr else 1 if {"HDR", "HDR10+"} & set(hdr) else 0,
            codec, "Atmos" in audio, 2 if "7.1" in ch else 1 if "5.1" in ch else 0, r["Seeders"])
DISC = re.compile(r"\b(bdmv|bd(?:25|50|66|100)|iso|complete[ ._-]+(?:uhd[ ._-]+)?blu-?ray)\b", re.I)  # BR-DISK
_YEAR, _SE = r"\b(?:19|20)\d{2}\b", r"\bs(\d{1,2})(?:e(\d{1,3}))?\b"


def norm(s):
    s = re.sub(r"[^\w]+", " ", s.lower().replace("&", " and ")).strip()
    return re.sub(r"^(the|a|an) ", "", s)


def same_title(parsed, wanted):
    """'Kimi no Na wa (Your Name)' matches 'Your Name'; 'The Walking Dead Daryl Dixon' does not match 'Walking Dead'."""
    names = {norm(x) for x in [parsed, *re.split(r"[()\[\]/|]|\baka\b", parsed, flags=re.I)]} - {""}
    return any(SequenceMatcher(None, a, b).ratio() >= 0.85 for a in names for b in wanted)


def original_audio(p, title, lang):
    """No burned-in subs, audio in the original language.
    ponytail: judged from title tags only; real audio/sub tracks are only knowable after fetching the files."""
    if p.get("hardcoded"):
        return False
    langs = p.get("languages") or []
    if langs and lang not in langs and not p.get("subbed"):  # e.g. a Japanese film tagged only 'en' = English dub
        return False
    return not (p.get("dubbed") and lang not in langs and not re.search(r"dual|multi", title, re.I))

_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _listening(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_up(timeout=90):
    """Start whichever services are down; return the processes started, so stop() can close only those."""
    procs = []
    for port, exe, env in SERVICES:
        if not _listening(port):
            if not exe:  # FlareSolverr is optional; Jackett is not
                if port == 9117:
                    sys.exit("Jackett is not running and no Jackett folder is configured: run install.py --jackett <dir>")
                continue
            print(f"starting {os.path.basename(exe)} ...", file=sys.stderr)
            hidden = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                      if os.name == "nt" else {"start_new_session": True})
            procs.append((port, subprocess.Popen(
                [exe], cwd=os.path.dirname(exe), env={**os.environ, **env},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden)))
    deadline, pending = time.time() + timeout, [p for p, _ in procs]
    while pending and time.time() < deadline:
        time.sleep(2)
        pending = [p for p in pending if not _listening(p)]
    if pending:
        stop(procs)
        sys.exit(f"Services on ports {pending} did not come up within {timeout}s")
    return procs


def stop(procs):
    for _, p in procs:  # whole tree: FlareSolverr leaves Chrome + chromedriver children behind otherwise
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            os.killpg(p.pid, __import__("signal").SIGKILL)


def api_key():
    return os.environ.get("JACKETT_API_KEY") or json.load(open(CONFIG, encoding="utf-8-sig"))["APIKey"]


def login():
    # Admin endpoints need the UI cookie; empty password works when none is set.
    pw = os.environ.get("JACKETT_PASSWORD", "")
    _op.open(urllib.request.Request(URL + "/UI/Dashboard", data=urllib.parse.urlencode({"password": pw}).encode()))


def call(path, method="GET", body=None, timeout=120):
    req = urllib.request.Request(URL + "/api/v2.0" + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with _op.open(req, timeout=timeout) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        try:
            msg = json.loads(msg).get("error", msg)
        except ValueError:
            pass
        sys.exit(f"HTTP {e.code} {path}: {msg[:500]}")
    if not data:
        return None
    try:
        return json.loads(data)
    except ValueError:  # redirected to login page -> wrong password
        sys.exit(f"Non-JSON reply from {path}; check JACKETT_PASSWORD")


def _bend(b, i):
    """Index just past the bencoded value starting at b[i]."""
    c = b[i:i + 1]
    if c == b"i":
        return b.index(b"e", i) + 1
    if c in (b"l", b"d"):
        i += 1
        while b[i:i + 1] != b"e":
            i = _bend(b, i)
        return i + 1
    n = b.index(b":", i)
    return n + 1 + int(b[i:n])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def to_magnet(link):
    """Turn a Jackett /dl link (.torrent or redirect-to-magnet) into a magnet URI; None on failure.
    Cloud downloaders like PikPak can't reach 127.0.0.1 links, so they need the magnet."""
    try:
        with urllib.request.build_opener(_NoRedirect).open(link, timeout=90) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        return loc if loc.startswith("magnet:") else None
    except Exception:
        return None
    if not data.startswith(b"d"):
        return None
    fields, i = {}, 1
    while data[i:i + 1] != b"e":  # walk the top-level dict, keep raw value bytes
        k_end = _bend(data, i)
        key = data[data.index(b":", i) + 1:k_end]
        i = _bend(data, k_end)
        fields[key] = data[k_end:i]
    if b"info" not in fields:
        return None
    m = "magnet:?xt=urn:btih:" + hashlib.sha1(fields[b"info"]).hexdigest()
    if b"announce" in fields:
        ann = fields[b"announce"]
        m += "&tr=" + urllib.parse.quote(ann[ann.index(b":") + 1:].decode(errors="ignore"), safe="")
    return m


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"


def cmd_list(a):
    login()
    rows = call("/indexers?configured=false")
    rows = [r for r in rows
            if (not a.configured or r["configured"]) and (not a.public or r["type"] == "public")
            and (not a.lang or r["language"].lower().startswith(a.lang.lower()))
            and (not a.grep or a.grep.lower() in (r["id"] + r["name"]).lower())]
    if a.json:
        return print(json.dumps(rows, ensure_ascii=False, indent=1))
    for r in rows:
        mark = "*" if r["configured"] else " "
        print(f"{mark} {r['id']:<28} {r['type']:<13} {r['language']:<6} {r['name']}")
    print(f"{len(rows)} indexers (* = configured)", file=sys.stderr)


def cmd_add(a):
    login()
    cfg = call(f"/indexers/{a.id}/config")
    sets = dict(s.split("=", 1) for s in a.set)
    for f in cfg:
        if f["id"] in sets:
            v = sets.pop(f["id"])
            f["value"] = v.lower() in ("1", "true", "yes") if f["type"] == "inputbool" else v
    if sets:
        sys.exit(f"Unknown fields {list(sets)}; available: {[f['id'] for f in cfg if 'value' in f]}")
    call(f"/indexers/{a.id}/config", "POST", cfg)  # Jackett tests the indexer while saving
    print(f"added {a.id}")


def cmd_remove(a):
    login()
    call(f"/indexers/{a.id}", "DELETE")
    print(f"removed {a.id}")


def cmd_test(a):
    login()
    call(f"/indexers/{a.id}/test", "POST")
    print(f"{a.id} OK")


def fetch(query, cat=None, indexers=None):
    q = [("apikey", api_key()), ("Query", query)]
    q += [("Tracker[]", t) for t in indexers.split(",")] if indexers else []
    q += [("Category[]", c) for c in cat.split(",")] if cat else []
    res = call("/indexers/all/results?" + urllib.parse.urlencode(q), timeout=300)
    for i in res["Indexers"]:
        if i.get("Error"):
            print(f"[{i['ID']}] error: {i['Error'].splitlines()[0][:200]}", file=sys.stderr)
    return res["Results"]


def refine(results, query, quality=None, clean=False, lang="en", titles=(), words=False):
    """Live, same-title, quality/clean-filtered, junk-free, cross-tracker-deduped; best tier first, then seeders.
    words=True matches by query words instead of title similarity (release codes, adult titles)."""
    ql = query.lower()
    years = [int(y) for y in re.findall(_YEAR, ql)]
    se = re.search(_SE, ql)
    wanted = {norm(t) for t in titles} | {norm(re.sub(f"{_YEAR}|{_SE}", " ", ql))}
    res_ok = RES.get(quality.lower(), {quality.lower()}) if quality else None
    items = []
    for r in results:
        if (r.get("Seeders") or 0) <= 0:  # dead torrents are useless
            continue
        p = r["_p"] = parse_title(r["Title"])
        if words:
            if not set(re.findall(r"\w+", ql)) <= set(re.findall(r"\w+", r["Title"].lower())):
                continue
        elif not same_title(p.get("title") or "", wanted) \
                or (years and p.get("year") and min(abs(p["year"] - y) for y in years) > 1) \
                or (se and int(se[1]) not in p.get("seasons", [])) \
                or (se and se[2] and int(se[2]) not in p.get("episodes", [])):
            continue
        if (res_ok and p.get("resolution") not in res_ok) \
                or p.get("trash") or p.get("upscaled") or p.get("3d") or DISC.search(r["Title"]) \
                or (clean and not original_audio(p, r["Title"], lang)):
            continue
        items.append(r)
    seen, uniq = set(), []  # same torrent shows up on several trackers; keep the best-seeded copy
    for r in sorted(items, key=lambda r: r["Seeders"], reverse=True):
        keys = {" ".join(re.findall(r"\w+", r["Title"].lower()))}
        keys |= {k for k in ((r.get("InfoHash") or "").lower(), r.get("Size")) if k}  # identical byte size = same files
        if not keys & seen:
            uniq.append(r)
        seen |= keys
    return sorted(uniq, key=rank, reverse=True)


def with_magnets(items, n):
    """Resolve 2n candidates to magnets, dedupe again on the now-known infohash, keep n."""
    items = items[:n * 2]
    need = [r for r in items if not r.get("MagnetUri") and r.get("Link")]
    with ThreadPoolExecutor(8) as ex:
        for r, m in zip(need, ex.map(lambda r: to_magnet(r["Link"]), need)):
            r["MagnetUri"] = m
    hashes, kept = set(), []
    for r in items:
        h = re.search(r"btih:(\w+)", r.get("MagnetUri") or "")
        h = h.group(1).lower() if h else id(r)
        if h not in hashes:
            kept.append(r)
        hashes.add(h)
    return kept[:n]


_KEEP = ("Tracker", "Title", "Size", "Seeders", "Peers", "PublishDate", "CategoryDesc", "MagnetUri", "Link", "Details")


_PARSED = ("resolution", "quality", "codec", "bit_depth", "hdr", "audio", "channels", "group", "languages",
           "seasons", "episodes", "complete")


def slim(items):
    return [{**{k: r.get(k) for k in _KEEP},
             "Parsed": {k: v for k, v in (r.get("_p") or {}).items() if k in _PARSED and v}} for r in items]


def per_resolution(items, cap):
    """Keep at most `cap` rows per resolution (Torrentio's 'max results per quality'), so 4K remuxes
    don't crowd every 1080p option out of a 1080p+ search."""
    seen, out = {}, []
    for r in items:
        k = r["_p"].get("resolution")
        seen[k] = seen.get(k, 0) + 1
        if seen[k] <= cap:
            out.append(r)
    return out


def cmd_search(a):
    results = fetch(a.query, a.cat, a.indexers)
    items = refine(results, a.query, a.quality, a.clean, a.lang, a.title, a.words)
    if (a.quality or "").lower() == "1080p+" and not a.best:
        items = per_resolution(items, -(-a.n // 2))
    items = with_magnets(items, a.n) if a.magnet else items[:a.n]
    if a.json:
        return print(json.dumps(slim(items), ensure_ascii=False, indent=1))
    for r in items:
        print(f"{r.get('Seeders') or 0:>6}S {human(r.get('Size') or 0):>9}  [{r['Tracker']}] {r['Title']}")
        print(f"        {r.get('MagnetUri') or r.get('Link')}")
    print(f"{len(items)}/{len(results)} results", file=sys.stderr)


def tvmaze(target):
    """Show + aired seasons from TVmaze (free, no key). target = IMDb id or show name."""
    base = "https://api.tvmaze.com"
    url = (f"{base}/lookup/shows?imdb={target}" if re.fullmatch(r"tt\d+", target)
           else f"{base}/singlesearch/shows?" + urllib.parse.urlencode({"q": target}))
    show = json.load(urllib.request.urlopen(url, timeout=20))
    today = __import__("datetime").date.today().isoformat()
    seasons = [s for s in json.load(urllib.request.urlopen(f"{base}/shows/{show['id']}/seasons", timeout=20))
               if s.get("premiereDate") and s["premiereDate"] <= today]
    return show, seasons, today


def classify(title):
    """('episode', (s, e)) | ('pack', {seasons}) | ('complete', None) | (None, None)"""
    p = parse_title(title)
    s, e = p.get("seasons") or [], p.get("episodes") or []
    if e:  # S01E01-E05 multi-episode packs: skip
        return ("episode", (s[0], e[0])) if len(s) == 1 and len(e) == 1 else (None, None)
    if s:
        return "pack", set(s)
    return ("complete", None) if p.get("complete") else (None, None)


def cmd_show(a):
    show, seasons, today = tvmaze(a.target)
    name = re.sub(r"[^\w\s]", " ", show["name"]).lower()
    nums = [s["number"] for s in seasons]
    queries = [f"{name} s{n:02d}" for n in nums] + [f"{name} complete", name]
    with ThreadPoolExecutor(4) as ex:  # ponytail: one Jackett query per season; slow for 20+ season shows
        results = [r for rs in ex.map(lambda q: fetch(q, "5000"), queries) for r in rs]
    items = refine(results, name, a.quality, a.clean)
    complete, packs, eps = [], {n: [] for n in nums}, {}
    for r in items:
        kind, val = classify(r["Title"])
        if kind == "complete" or (kind == "pack" and set(nums) <= val):
            complete.append(r)
        elif kind == "pack" and len(val) == 1 and (n := next(iter(val))) in packs:
            packs[n].append(r)
        elif kind == "episode" and val[0] in packs:
            eps.setdefault(val, []).append(r)
    out = {"show": show["name"], "imdb": show["externals"].get("imdb"), "status": show["status"],
           "complete": slim(with_magnets(complete, a.n)), "seasons": []}
    for s in seasons:
        n = s["number"]
        entry = {"season": n, "episodes": s.get("episodeOrder"),
                 "airing": not s.get("endDate") or s["endDate"] >= today,
                 "packs": slim(with_magnets(packs[n], a.n)), "by_episode": []}
        if not entry["packs"]:  # no season pack yet (airing / obscure): best copy of each episode
            for (sn, e) in sorted(k for k in eps if k[0] == n):
                best = with_magnets(eps[(sn, e)], 1)
                if best:
                    entry["by_episode"].append({"episode": e, **slim(best)[0]})
        out["seasons"].append(entry)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description="Jackett CLI")
    s = p.add_subparsers(dest="cmd", required=True)
    l = s.add_parser("list"); l.set_defaults(f=cmd_list)
    l.add_argument("--configured", action="store_true"); l.add_argument("--public", action="store_true")
    l.add_argument("--lang"); l.add_argument("--grep"); l.add_argument("--json", action="store_true")
    ad = s.add_parser("add"); ad.set_defaults(f=cmd_add)
    ad.add_argument("id"); ad.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    for name, fn in (("remove", cmd_remove), ("test", cmd_test)):
        x = s.add_parser(name); x.set_defaults(f=fn); x.add_argument("id")
    se = s.add_parser("search"); se.set_defaults(f=cmd_search)
    se.add_argument("query"); se.add_argument("-i", "--indexers", help="comma-separated ids, default all configured")
    se.add_argument("-c", "--cat", help="Torznab categories, e.g. 2000=Movies 5000=TV")
    se.add_argument("-q", "--quality", help="1080p+ (1080p or 4k), 2160p/4k, 1080p, 720p, 480p, or any literal tag")
    se.add_argument("--clean", action="store_true", help="drop dubbed and hardsubbed releases")
    se.add_argument("--lang", default="en", help="original audio language (ISO 639-1) for --clean, e.g. ja")
    se.add_argument("--title", action="append", default=[], help="canonical title / alias to match; repeatable")
    se.add_argument("--words", action="store_true", help="match by query words, not title similarity (codes)")
    se.add_argument("--best", action="store_true", help="pure quality ranking: no per-resolution cap")
    se.add_argument("--magnet", action="store_true", help="resolve .torrent-only results to magnet links")
    se.add_argument("-n", type=int, default=20); se.add_argument("--json", action="store_true")
    sh = s.add_parser("show", help="season packs + complete-series packs for a TV show (JSON)")
    sh.set_defaults(f=cmd_show); sh.add_argument("target", help="IMDb id (tt...) or show name")
    sh.add_argument("-q", "--quality", default="1080p+"); sh.add_argument("--clean", action="store_true")
    sh.add_argument("-n", type=int, default=2, help="results per season / complete group")
    a = p.parse_args()
    procs = ensure_up()
    try:
        a.f(a)
    finally:  # the user wants nothing left running after a command
        stop(procs)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
