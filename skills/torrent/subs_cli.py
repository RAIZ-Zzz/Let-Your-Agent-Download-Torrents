r"""More Chinese subtitle sources for /torrent when SubHD has none (mostly anime).

  python subs_cli.py share "葬送的芙莉莲" --year 2023                # foxofice/sub_share archive: subtitle folders
  python subs_cli.py share-get "<folder path>" --dest DIR [--grep "\[05\]"]
  python subs_cli.py assrt "Sousou no Frieren" [-n 15]               # assrt.net (free token required)
  python subs_cli.py assrt-get <id> --dest DIR
  python subs_cli.py xunlei "<release title or file name>" --dest DIR [-n 1]   # Thunder player search, no login
  python subs_cli.py acgrip "芙莉莲"                                  # bbs.acgrip.com (Anime字幕论坛) threads
  python subs_cli.py acgrip-get <tid> --dest DIR [--grep "\[05\]"]      # attachments; needs a login cookie

sub_share stopped updating in Sep 2025. GITHUB_TOKEN (optional) lifts GitHub's 60 requests/hour limit.
assrt.net token: register at assrt.net, copy the API token from the user panel, then set ASSRT_TOKEN
or "assrt_token" in config.json next to this file.
"""
import argparse, html, json, os, re, sys, urllib.parse, urllib.request
from subhd_cli import save

HERE = os.path.dirname(os.path.abspath(__file__))
_CFG = os.path.join(HERE, "config.json")
CFG = json.load(open(_CFG, encoding="utf-8")) if os.path.exists(_CFG) else {}
REPO = "https://api.github.com/repos/foxofice/sub_share"
SUB_EXT = (".ass", ".ssa", ".srt", ".zip", ".7z", ".rar")
ZH = {"langdou": 3, "langchs": 2, "langcht": 1}  # assrt language flags: 双语 > 简体 > 繁体


def fetch(url, headers=None):
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@~")  # download URLs from both sites carry raw Chinese file names
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})}),
                                  timeout=60).read()


def gh(path):
    tok = os.environ.get("GITHUB_TOKEN")
    return json.loads(fetch(REPO + path, {"Authorization": f"Bearer {tok}"} if tok else {}))


def cmd_share(a):
    """Every folder that directly holds subtitle files, under title folders matching all query words (±1 year)."""
    words = a.query.lower().split()
    out = []
    for y in range(a.year - 1, a.year + 2):
        try:
            shows = gh(f"/contents/subs_list/animation/{y}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        for show in shows:
            if show["type"] != "dir" or not all(w in show["name"].lower() for w in words):
                continue
            folders = {}
            for t in gh(f"/git/trees/{show['sha']}?recursive=1")["tree"]:
                if t["type"] == "blob" and t["path"].lower().endswith(SUB_EXT):
                    folders.setdefault(os.path.dirname(t["path"]), []).append(os.path.basename(t["path"]))
            for d, fs in sorted(folders.items()):
                out.append({"path": f"{show['path']}/{d}".rstrip("/"), "files": len(fs), "sample": sorted(fs)[:2]})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_share_get(a):
    files = [f for f in gh("/contents/" + urllib.parse.quote(a.path))
             if f["type"] == "file" and f["name"].lower().endswith(SUB_EXT) and re.search(a.grep or "", f["name"])]
    if not files:
        sys.exit("No subtitle files in that folder" + (f" matching {a.grep!r}" if a.grep else ""))
    for f in files:
        got = save(fetch(f["download_url"]), os.path.splitext(f["name"])[1], os.path.splitext(f["name"])[0], a.dest)
    print(json.dumps({"dest": a.dest, "files": got}, ensure_ascii=False, indent=1))


def assrt(endpoint, **q):
    tok = os.environ.get("ASSRT_TOKEN") or CFG.get("assrt_token")
    if not tok:
        sys.exit("assrt.net needs a free API token: register at https://assrt.net, copy the token from the user panel, "
                 "then set ASSRT_TOKEN or add \"assrt_token\" to " + _CFG)
    try:
        d = json.loads(fetch(f"https://api.assrt.net/v1/{endpoint}?" + urllib.parse.urlencode({"token": tok, **q})))
    except urllib.error.HTTPError as e:  # client/server errors come as 4xx/5xx with the same JSON body
        d = json.loads(e.read() or b"{}") or {"status": e.code}
    if d.get("status"):
        sys.exit(f"assrt.net error {d['status']}: {d.get('errmsg', '')}")
    return d["sub"]["subs"]


def cmd_assrt(a):
    """Chinese subtitles only, in assrt's relevance order."""
    out = [{"id": s["id"], "name": s.get("native_name"), "video": s.get("videoname"), "group": s.get("release_site"),
            "lang": (s.get("lang") or {}).get("desc"), "type": s.get("subtype"), "date": s.get("upload_time"),
            "score": s.get("vote_score")}
           for s in assrt("sub/search", q=a.query, cnt=a.n)
           if set(((s.get("lang") or {}).get("langlist") or {})) & set(ZH)]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_assrt_get(a):
    s = assrt("sub/detail", id=a.id)[0]
    name, ext = os.path.splitext(s["filename"])
    print(json.dumps({"dest": a.dest, "files": save(fetch(s["url"]), ext, name, a.dest)}, ensure_ascii=False, indent=1))


KANA, HAN = re.compile(r"[\u3040-\u30ff]"), re.compile(r"[\u4e00-\u9fff]")


def lines(raw):
    """Spoken text lines of an ASS/SSA/SRT file, whatever its encoding."""
    for enc in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            t = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []
    if "[Events]" in t:
        return [l.split(",", 9)[-1] for l in t.splitlines() if l.startswith("Dialogue:")]
    return [l for l in t.splitlines() if l.strip() and "-->" not in l and not l.strip().isdigit()]


def chinese(raw):
    """At least 30% of lines are Han text without kana: Chinese, alone or beside Japanese / English lines.
    ponytail: share of lines only; a Japanese file with many kanji-only lines could slip through."""
    ls = lines(raw)
    return bool(ls) and sum(bool(HAN.search(l)) and not KANA.search(l) for l in ls) >= 0.3 * len(ls)


def cmd_xunlei(a):
    """Thunder's player subtitle search by video name: unofficial, unlabeled, unreviewed, so each candidate
    is downloaded and kept only if its text is Chinese. Tagged 简体/双语/中文 first, then the API's order."""
    data = json.loads(fetch("https://api-shoulei-ssl.xunlei.com/oracle/subtitle?" + urllib.parse.urlencode(
        {"name": a.query}))).get("data") or []
    tagged = lambda s: any(k in "".join(s.get("languages") or []) + (s.get("simple_name") or "")
                           for k in ("简", "双语", "中文", "中英", "chs"))
    seen, kept, checked = set(), [], 0
    for s in sorted(data, key=lambda s: not tagged(s)):
        ext = "." + (s.get("ext") or "").lower()
        if s["gcid"] in seen or ext not in (".ass", ".ssa", ".srt") or checked >= 15 or len(kept) >= a.n:
            continue
        seen.add(s["gcid"]); checked += 1
        try:
            raw = fetch(s["url"])
        except (urllib.error.URLError, TimeoutError):  # some indexed files are gone from Thunder's CDN
            continue
        if raw not in seen and chinese(raw):  # the same file is often indexed under several ids
            seen.add(raw)
            name = f"{s.get('simple_name') or s['name']}.{s['gcid'][:6]}"
            save(raw, ext, name, a.dest)
            kept.append(name + ext)
    if not kept:
        sys.exit(f"No Chinese subtitle among {checked} Thunder results for {a.query!r}")
    print(json.dumps({"dest": a.dest, "checked": checked, "files": kept}, ensure_ascii=False, indent=1))


ACG = "https://bbs.acgrip.com/"


def secret(key):
    return os.environ.get(key.upper()) or CFG.get(key)


def page(url, cookie=None):
    return fetch(url, {"Cookie": cookie} if cookie else {}).decode("utf-8", "replace")


def text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def discuz_msg(t):
    m = re.search(r'id="messagetext"[^>]*>\s*<p>(.*?)</p>', t, re.S)
    return text(m[1]) if m else None


def cmd_acgrip(a):
    """Anime字幕论坛 thread search (works logged out)."""
    t = page(ACG + "search.php?" + urllib.parse.urlencode({"mod": "forum", "srchtxt": a.query, "searchsubmit": "yes"}),
             secret("acgrip_cookie"))
    out = [{"tid": tid, "title": text(title), "stats": text(stats), "snippet": re.sub(r"\s+", " ", text(snip))[:120], "date": date,
            "forum": text(forum)}
           for tid, title, stats, snip, date, forum in re.findall(
               r'<li class="pbw" id="(\d+)">.*?<a [^>]*>(.*?)</a>.*?<p class="xg1">(.*?)</p>\s*<p>(.*?)</p>'
               r'.*?<span>([\d-]+ [\d:]+)</span>.*?class="xi1">(.*?)</a>', t, re.S)]
    if not out and discuz_msg(t):
        sys.exit(f"acgrip: {discuz_msg(t)}")
    print(json.dumps(out[:a.n], ensure_ascii=False, indent=1))


def cmd_acgrip_get(a):
    """Download a thread's attachments (needs the logged-in cookie) and list any cloud-drive links it posts."""
    cookie = secret("acgrip_cookie")
    if not cookie:
        sys.exit("bbs.acgrip.com attachments need a login: log in in your browser, copy the Cookie request header "
                 "(F12 > Network > any bbs.acgrip.com request), then set ACGRIP_COOKIE or \"acgrip_cookie\" in " + _CFG)
    t = page(ACG + f"forum.php?mod=viewthread&tid={a.tid}", cookie)
    if "您需要登录" in t or "mod=logging&amp;action=login" in t and "action=logout" not in t:
        sys.exit("bbs.acgrip.com says you are not logged in: the cookie expired, copy it again")
    links = sorted(set(re.findall(r'https?://(?:pan\.baidu\.com|www\.alipan\.com|www\.aliyundrive\.com|pan\.quark\.cn|'
                                  r'cloud\.189\.cn|pan\.xunlei\.com|mega\.nz|drive\.google\.com|1drv\.ms)[^\s"<>]*', t)))
    codes = sorted(set(re.findall(r"(?:提取码|密码|pwd)[:：\s]*([A-Za-z0-9]{4})", text(t))))
    atts = [(html.unescape(u), text(n)) for u, n in
            re.findall(r'href="(forum\.php\?mod=attachment&amp;aid=[^"]+)"[^>]*>(.*?)</a>', t, re.S)]
    atts = [(u, n) for u, n in dict(atts).items() if n.lower().endswith(SUB_EXT) and re.search(a.grep or "", n)]
    files = []
    for u, n in atts:
        raw = fetch(ACG + u, {"Cookie": cookie})
        if raw[:200].lstrip().lower().startswith((b"<!doctype", b"<html", b"<?xml")):
            sys.exit(f"acgrip refused {n}: {discuz_msg(raw.decode('utf-8', 'replace')) or 'HTML instead of a file'}")
        files = save(raw, os.path.splitext(n)[1], os.path.splitext(n)[0], a.dest)
    print(json.dumps({"dest": a.dest, "attachments": [n for _, n in atts], "files": files,
                      "links": links, "codes": codes}, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description="sub_share + assrt.net subtitle CLI for /torrent")
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("share"); x.set_defaults(f=cmd_share); x.add_argument("query"); x.add_argument("--year", type=int, required=True)
    x = s.add_parser("share-get"); x.set_defaults(f=cmd_share_get); x.add_argument("path")
    x.add_argument("--dest", required=True); x.add_argument("--grep", help="regex on file names, e.g. an episode number")
    x = s.add_parser("assrt"); x.set_defaults(f=cmd_assrt); x.add_argument("query"); x.add_argument("-n", type=int, default=15)
    x = s.add_parser("assrt-get"); x.set_defaults(f=cmd_assrt_get); x.add_argument("id")
    x.add_argument("--dest", required=True)
    x = s.add_parser("xunlei"); x.set_defaults(f=cmd_xunlei); x.add_argument("query")
    x.add_argument("--dest", required=True); x.add_argument("-n", type=int, default=1, help="Chinese subtitles to keep")
    x = s.add_parser("acgrip"); x.set_defaults(f=cmd_acgrip); x.add_argument("query"); x.add_argument("-n", type=int, default=15)
    x = s.add_parser("acgrip-get"); x.set_defaults(f=cmd_acgrip_get); x.add_argument("tid")
    x.add_argument("--dest", required=True); x.add_argument("--grep", help="regex on attachment names")
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
