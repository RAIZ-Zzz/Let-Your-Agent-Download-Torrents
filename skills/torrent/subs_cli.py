r"""More Chinese subtitle sources for /torrent when SubHD has none (mostly anime).

  python subs_cli.py share "葬送的芙莉莲" --year 2023                # foxofice/sub_share archive: subtitle folders
  python subs_cli.py share-get "<folder path>" --dest DIR [--grep "\[05\]"]
  python subs_cli.py assrt "Sousou no Frieren" [-n 15]               # assrt.net (free token required)
  python subs_cli.py assrt-get <id> --dest DIR

sub_share stopped updating in Sep 2025. GITHUB_TOKEN (optional) lifts GitHub's 60 requests/hour limit.
assrt.net token: register at assrt.net, copy the API token from the user panel, then set ASSRT_TOKEN
or "assrt_token" in config.json next to this file.
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request
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


def main():
    p = argparse.ArgumentParser(description="sub_share + assrt.net subtitle CLI for /torrent")
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("share"); x.set_defaults(f=cmd_share); x.add_argument("query"); x.add_argument("--year", type=int, required=True)
    x = s.add_parser("share-get"); x.set_defaults(f=cmd_share_get); x.add_argument("path")
    x.add_argument("--dest", required=True); x.add_argument("--grep", help="regex on file names, e.g. an episode number")
    x = s.add_parser("assrt"); x.set_defaults(f=cmd_assrt); x.add_argument("query"); x.add_argument("-n", type=int, default=15)
    x = s.add_parser("assrt-get"); x.set_defaults(f=cmd_assrt_get); x.add_argument("id")
    x.add_argument("--dest", required=True)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
