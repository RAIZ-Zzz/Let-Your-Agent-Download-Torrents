r"""SubHD helper for /torrent: pick the best Chinese subtitle for a release and save it locally.

  python subhd_cli.py find "你的名字" [--year 2016]                       # SubHD entries (id = Douban id)
  python subhd_cli.py list 26683290 --release "<torrent title>" [-n 5]   # ranked subtitles
  python subhd_cli.py get 26683290 --release "<torrent title>" --dest "B:\videos\Your Name (2016)" [--sid X]
"""
import argparse, html, http.cookiejar, json, os, re, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request
from PTT import parse_title  # pip install parsett

BASE = "https://subhd.me"
UA = {"User-Agent": "Mozilla/5.0"}
SOURCE = {"精选推荐": 4, "官方字幕": 3, "原创翻译": 2, "AI校对": 1}  # anything else (其他来源 …) = 0
LANG = {"双语": 3, "简体": 2, "繁体": 1}  # Chinese required; bilingual first
TEXT_FORMATS = {"SRT", "ASS", "SSA"}  # SUP is image-based and most players can't load it


_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))  # the download
# steps are tied together by the session cookie; without it the second step answers "临时页面已经失效"


def get(path):
    return _op.open(urllib.request.Request(BASE + path, headers=UA), timeout=20).read().decode()


def post(path, body, referer):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), method="POST",
                                 headers={**UA, "Content-Type": "application/json", "Referer": BASE + referer})
    return json.load(_op.open(req, timeout=20))


def family(title):
    q = (parse_title(title).get("quality") or "").lower()
    return "bd" if re.search(r"blu|remux|bd", q) else "web" if "web" in q else None


def subtitles(film_id):
    page = get(f"/d/{film_id}")
    out = []
    for row in page.split('<div class="row pt-2 mb-2">')[1:]:
        if not (m := re.search(r'href="/a/(\w+)">(.*?)</a>', row)):
            continue
        tags = re.search(r'<div class="pt-1 f11">(.*?)</div>', row, re.S)
        tags = tags[1] if tags else ""
        dl = re.search(r'text-end text-secondary">\s*(\d+)', row)
        out.append({"sid": m[1], "title": html.unescape(m[2]).strip(),
                    "group": html.unescape((re.search(r'href="/zu/\d+"[^>]*>(.*?)</a>', row) or [None, ""])[1]),
                    "source": re.findall(r'text-white"[^>]*>([^<]+)<', tags),
                    "langs": re.findall(r'fw-bold">([^<]+)<', tags),
                    "formats": re.findall(r'text-secondary">([A-Z]+)<', tags),
                    "downloads": int(dl[1]) if dl else 0,
                    "date": (re.search(r'datetime="(\d{4}-\d\d-\d\d)', row) or [None, None])[1]})
    return out


def rank(subs, release):
    """Season pack for a season-pack torrent > same source family (BD vs WEB timing) > trust > Chinese language
    > exact release group > downloads."""
    rp = parse_title(release)
    fam, grp, eps = family(release), (rp.get("group") or "").lower(), set(rp.get("episodes") or [])
    pack = bool(rp.get("seasons")) and not eps
    keep = [s for s in subs if set(s["langs"]) & set(LANG) and set(s["formats"]) & TEXT_FORMATS]
    if eps:  # an episode torrent: that episode's subtitle, or a season pack (no episode in its title)
        keep = [s for s in keep if not (e := set(parse_title(s["title"]).get("episodes") or [])) or eps & e]
    return sorted(keep, reverse=True, key=lambda s: (
        pack and not parse_title(s["title"]).get("episodes"),
        fam is not None and family(s["title"]) == fam,
        max([SOURCE.get(t, 0) for t in s["source"]] + [0]),
        max(LANG.get(l, 0) for l in s["langs"]),
        bool(grp) and (parse_title(s["title"]).get("group") or "").lower() == grp,
        s["downloads"]))


def direct_url(sid):
    """The site's own two-step download flow; stops (no workaround) if it asks for verification."""
    get(f"/a/{sid}")
    prep = post("/api/sub/prepare-download", {"sid": sid}, f"/a/{sid}")
    if not prep.get("success"):
        return None, prep.get("msg")
    get(prep["url"])
    down = post("/api/sub/down", {"sid": sid}, prep["url"])
    return (down["url"], None) if down.get("pass") else (None, down.get("msg"))


def cmd_find(a):
    d = json.loads(get("/searchD/" + urllib.parse.quote(a.query)))
    out = []
    for fid, name in re.findall(r'href="/d/(\d+)">(.*?)</a>', d.get("text", "")):
        name = html.unescape(name)
        y = re.search(r"\((\d{4})\)\s*$", name)
        if not a.year or (y and abs(int(y[1]) - a.year) <= 1):
            out.append({"id": fid, "name": name, "year": int(y[1]) if y else None})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_list(a):
    print(json.dumps(rank(subtitles(a.id), a.release)[:a.n], ensure_ascii=False, indent=1))


def cmd_get(a):
    """Download the chosen (or best-ranked) subtitle into dest; archives are unpacked with Windows' bsdtar."""
    ranked = rank(subtitles(a.id), a.release)
    pick = next((s for s in ranked if s["sid"] == a.sid), None) if a.sid else (ranked[0] if ranked else None)
    if not pick:
        sys.exit("No Chinese text subtitle found" if not a.sid else f"sid {a.sid} not on this page")
    url, err = direct_url(pick["sid"])
    if not url:
        sys.exit(f"SubHD refused the download: {err}")
    os.makedirs(a.dest, exist_ok=True)
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext in (".srt", ".ass", ".ssa"):
        open(os.path.join(a.dest, f"{pick['title'][:150]}{ext}"), "wb").write(data)
    else:  # zip / 7z / rar; bsdtar refuses absolute and ../ paths by default
        with tempfile.TemporaryDirectory() as tmp:
            arc = os.path.join(tmp, "sub" + ext)
            open(arc, "wb").write(data)
            # ponytail: zip names without the UTF-8 flag are read as GBK (SubHD uploads come from Chinese Windows);
            # a non-flagged UTF-8 zip (e.g. from macOS) would garble, detect per entry if that shows up
            gbk = ["--options", "hdrcharset=CP936"] if ext == ".zip" else []
            tar = (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe") if os.name == "nt"
                   else "bsdtar" if shutil.which("bsdtar") else "tar")  # needs bsdtar (macOS: built in; Linux: libarchive-tools)
            subprocess.run([tar, *gbk, "-xf", arc, "-C", a.dest], check=True)
    files = [os.path.relpath(os.path.join(d, f), a.dest) for d, _, fs in os.walk(a.dest) for f in fs]
    print(json.dumps({**pick, "dest": a.dest, "files": files}, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description="SubHD CLI for /torrent")
    s = p.add_subparsers(dest="cmd", required=True)
    f = s.add_parser("find"); f.set_defaults(f=cmd_find)
    f.add_argument("query"); f.add_argument("--year", type=int)
    for name, fn in (("list", cmd_list), ("get", cmd_get)):
        b = s.add_parser(name); b.set_defaults(f=fn)
        b.add_argument("id", help="SubHD /d/ id (Douban id)"); b.add_argument("--release", default="", help="torrent title")
        if fn is cmd_list:
            b.add_argument("-n", type=int, default=5)
        else:
            b.add_argument("--dest", required=True); b.add_argument("--sid", help="pick this subtitle instead of the best")
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
