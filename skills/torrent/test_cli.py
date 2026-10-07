"""Offline checks for title filtering/ranking and subtitle ranking: python test_cli.py"""
import jackett_cli as j  # offline: imports only, no Jackett needed


def kept(names, query, lang="en", quality="1080p+", **kw):
    rs = [{"Title": t, "Seeders": 10 + i, "Size": i} for i, t in enumerate(names)]
    return [r["Title"] for r in j.refine(rs, query, quality, True, lang, **kw)]


your_name = {
    "Your.Name.2016.1080p.BluRay.x264-HAiKU": True,
    "Kimi no Na wa. (Your Name.) 2016 2160p UHD BluRay REMUX HDR HEVC Dual Audio TrueHD-FraMeSToR": True,
    "[Judas] Kimi no Na wa (Your Name) (BD 2160p 4K UHD HEVC x265 10bit) [Dual-Audio][Multi-Subs]": True,
    "Your.Name.2016.1080p.BluRay.ITA.JPN.DTS-HD": True,
    "君の名は。 Your Name 2016 1080p BluRay": True,
    "Your Name 2016 1080p BluRay English Dubbed x264": False,     # dub only
    "你的名字 Your.Name.2016.1080p.BluRay.x264.HC.中英字幕": False,   # hardsub
    "Твоё имя Your Name 2016 BDRip 1080p Dub": False,             # Russian dub
    "Your Name 2016 COMPLETE BLURAY BDMV 1080p AVC DTS-HD MA": False,  # BR-DISK
    "Your Name 2016 1080p HDCAM": False,
    "Your Name 2016 2160p AI Upscale": False,
    "Your Name 2016 720p BluRay": False,
    "Your Name Is Bond 2016 1080p WEB": False,                    # different title
    "Your Name 1985 1080p BluRay": False,                         # different year
}
got = kept(list(your_name), "your name 2016", "ja", titles=["Your Name", "Kimi no Na wa"])
assert set(got) == {t for t, ok in your_name.items() if ok}, sorted(set(got) ^ {t for t, ok in your_name.items() if ok})
assert got[0].startswith("Kimi no Na wa. (Your Name.) 2016 2160p"), got  # 2160p remux tops 1080p despite fewer seeders

assert kept(["Star Wars Una Nuova Speranza 1977 1080p BluRay", "Star.Wars.Episode.IV.A.New.Hope.1977.1080p.BluRay",
             "Star Wars A New Hope 1977 1080p"], "star wars a new hope 1977",
            titles=["Star Wars: Episode IV - A New Hope"]) == ["Star.Wars.Episode.IV.A.New.Hope.1977.1080p.BluRay",
                                                               "Star Wars A New Hope 1977 1080p"]  # BluRay tier first
assert kept(["The Walking Dead Daryl Dixon S01 2160p WEB h265", "The.Walking.Dead.S01E03.2160p.WEB",
             "The.Walking.Dead.S02E03.2160p.WEB", "The Walking Dead S01 2160p BluRay iris2"],
            "walking dead s01", quality="4k") == ["The.Walking.Dead.S01E03.2160p.WEB"]
assert kept(["The French Dispatch 2021 1080p BluRay"], "the french dispatch 2021") == ["The French Dispatch 2021 1080p BluRay"]
# low-seed rows sink below healthy ones even at higher quality
rs = [{"Title": "Dune 2021 2160p BluRay REMUX", "Seeders": 2, "Size": 1}, {"Title": "Dune 2021 1080p WEB", "Seeders": 50, "Size": 2}]
assert [r["Title"] for r in j.refine(rs, "dune 2021", "1080p+")][0] == "Dune 2021 1080p WEB"

rs = j.refine([{"Title": f"Dune 2021 {q} BluRay {i}", "Seeders": 50 + i, "Size": hash((q, i))} for q in ("2160p", "1080p") for i in range(8)],
              "dune 2021", "1080p+")
assert [r["_p"]["resolution"] for r in j.per_resolution(rs, 3)] == ["2160p"] * 3 + ["1080p"] * 3

# picture: DV beats plain remux even with fewer seeders; audio: lossless > lossy, Atmos, then channels
order = lambda ts: [r["Title"] for r in j.refine([{"Title": t, "Seeders": 60 - i, "Size": i} for i, t in enumerate(ts)],
                                                 "dune 2021", "1080p+")]
assert order(["Dune 2021 2160p BluRay REMUX HEVC DTS-HD MA 5.1-FGT", "Dune 2021 2160p BluRay REMUX DV HDR HEVC DTS-HD MA 5.1"]
             )[0].endswith("DV HDR HEVC DTS-HD MA 5.1")
assert order(["Dune 2021 2160p BluRay x265 HDR DDP 5.1", "Dune 2021 2160p BluRay x265 HDR DTS-HD MA 5.1",
              "Dune 2021 2160p BluRay x265 HDR TrueHD Atmos 7.1"]) == [
    "Dune 2021 2160p BluRay x265 HDR TrueHD Atmos 7.1", "Dune 2021 2160p BluRay x265 HDR DTS-HD MA 5.1",
    "Dune 2021 2160p BluRay x265 HDR DDP 5.1"]

c = j.classify
assert c("Breaking.Bad.S01.1080p.BluRay.x265") == ("pack", {1})
assert c("Breaking Bad Season 3 Complete 1080p") == ("pack", {3})
assert c("Breaking.Bad.S01-S05.COMPLETE.1080p") == ("pack", {1, 2, 3, 4, 5})
assert c("Breaking.Bad.S02E05.1080p.WEB") == ("episode", (2, 5))
assert c("Breaking Bad S01E01-E07 1080p") == (None, None)
assert c("Breaking Bad The Complete Series 1080p") == ("complete", None)

# anime: fansub 内封 = Chinese soft subs (kept, Japanese audio); 简体/内嵌/CHS without 内封 = burned in (dropped)
frieren = {
    "[绿茶字幕组] 葬送的芙莉莲 第二季 / Sousou no Frieren S2 [38][WebRip][1080p][简繁日内封]": True,
    "[喵萌奶茶屋&LoliHouse] 葬送的芙莉莲 / Sousou no Frieren - 01 [WebRip 1080p HEVC-10bit AAC][简繁日内封字幕]": True,
    "[9volt] Sousou no Frieren - 37 (S02E09) (WEB 1080p HEVC EAC-3)": True,
    "[桜都字幕组] 葬送的芙莉莲 / Sousou no Frieren [01][1080p][简体内嵌]": False,
    "[某字幕组] Sousou no Frieren [01][1080P][简体][MP4]": False,
}
got = kept(list(frieren), "sousou no frieren", "ja", titles=["Frieren", "Sousou no Frieren", "葬送的芙莉莲"])
assert set(got) == {t for t, ok in frieren.items() if ok}, sorted(set(got) ^ {t for t, ok in frieren.items() if ok})
assert kept(["阿索卡第一季.2023.S01E08.End.HD1080P.AAC.H264.CHS-ENG.BTSJ6"], "ahsoka", titles=["Ahsoka", "阿索卡"]) == []
an = lambda seeds, anime: [r["Title"][:6] for r in j.refine(
    [{"Title": t, "Seeders": s, "Size": i} for i, (t, s) in enumerate(zip(list(frieren)[:3], seeds))],
    "sousou no frieren", "1080p+", True, "ja", ["Sousou no Frieren"], anime=anime)]
assert an((10, 6, 136), True) == ["[绿茶字幕组", "[喵萌奶茶屋", "[9volt"]   # healthy 内封 above a better-seeded English release
assert an((10, 6, 136), False)[0] == "[9volt"                        # off by default
assert an((2, 1, 136), True)[0] == "[9volt"                          # a dying 内封 swarm does not jump the queue


# SubHD ranking (offline): Chinese text subs only, same source family first, then trust, language, group, downloads
import subhd_cli as sh
S = lambda sid, title, src=(), langs=("简体",), fmts=("ASS",), dl=0: {"sid": sid, "title": title, "source": list(src),
                                                                     "langs": list(langs), "formats": list(fmts), "downloads": dl}
subs = [S("web", "Show.S01E03.1080p.WEB-DL", ["官方字幕"], dl=900), S("bd", "Show.S01E03.1080p.BluRay-GRP", dl=10),
        S("sup", "Show.S01E03.1080p.BluRay", ["精选推荐"], fmts=["SUP"]), S("en", "Show.S01E03.1080p.BluRay", langs=["英语"]),
        S("e04", "Show.S01E04.1080p.BluRay", ["精选推荐"]), S("pack", "Show.S01.1080p.BluRay", ["原创翻译"], ["双语"])]
assert [s["sid"] for s in sh.rank(subs, "Show.S01E03.2160p.BluRay.x265-GRP")] == ["pack", "bd", "web"]
# download.py: one launch per magnet, argv intact; OS handler when no client; batch files and non-magnets refused
import download as dl
calls = []
dl.subprocess.Popen = lambda argv, **kw: calls.append(argv)
dl.os.startfile = lambda m: calls.append(["startfile", m])
mags = ["magnet:?xt=urn:btih:abc&dn=A%20B&tr=udp%3A%2F%2Fx", "magnet:?xt=urn:btih:def"]
dl.launch(mags, "C:/qbt/qbittorrent.exe")
assert calls == [["C:/qbt/qbittorrent.exe", m] for m in mags], calls
calls.clear(); dl.launch(mags[:1])
assert calls == ([["startfile", mags[0]]] if dl.os.name == "nt" else [[calls[0][0], mags[0]]]), calls
for bad in ((mags, "C:/x/client.BAT"), (["C:/Windows/System32/calc.exe"], None)):
    try:
        dl.launch(*bad); raise AssertionError(bad)
    except SystemExit:
        pass
print("all ok")
