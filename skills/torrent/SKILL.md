---
name: torrent
description: Search a local Jackett for live 1080p-or-better torrents of a movie or TV show, by IMDb ID (tt1234567) or title; original audio only, no hardcoded subs, most-seeded first; after the user picks rows, sends their magnets to the user's torrent client and fetches Chinese subtitles. Adult mode with an `18+` argument. Use when the user types "/torrent <imdb id | title> [2160p] [18+]" (e.g. "/torrent tt1160419", "/torrent Dune Part Two 4k") or asks to find a torrent / magnet for a film or show.
argument-hint: <imdb id tt... | title | code> [2160p|4k|最好] [18+]
---

# /torrent

User's standing requirements: **1080p or better** (never show lower), **original-language audio** (no dubs, even if a Chinese dub exists), **no hardcoded subtitles** (they add their own), **most seeders**. Downloads go through the user's **torrent client**: show the results, let the user pick, then send the picks to it (step 6). Never send anything before the user picks.

## Arguments

- Quality: default `1080p+` (1080p and 4K). If the user adds `2160p` / `4k` / `uhd`, use `4k` (4K only). A trailing `1080p` means `1080p` only. Never go below 1080p.
- Target: an IMDb ID (`tt` + digits, also accept a full imdb.com URL) or a title.
- Best mode: the user says `最好` / `best` / `画质最好` / `音质最好` / `最高画质`. Add `--best -n 3` to the search (pure quality ranking, no per-resolution cap; never below 1080p): resolution → Remux > BluRay > WEB → Dolby Vision > HDR > SDR → lossless audio (TrueHD / DTS-HD MA / FLAC / PCM; a Remux counts as lossless) > DD+ / DTS > DD > AAC → Atmos → 7.1 > 5.1 → seeders, with <5-seeder rows always last. Show only those 3 rows. For a non-English film add one line: the Atmos/lossless tag may belong to the dub track — the original-language track on some discs is lossless 5.1 without Atmos; titles can't tell.
- Adult mode: the user adds `18+` / `成人` / `xxx`. Then: skip the IMDb lookup and English-title rewrite (search the user's words or release code as given, e.g. `ssis 001`); search category `6000` instead of `2000,5000` with `--words` (match query words / release code instead of title similarity); **drop `--clean`** (adult titles are often Japanese/Chinese and dubs/subs don't apply); keep the quality filter; in step 4 only drop wrong-item / no-magnet rows (foreign titles are fine). Zero results → say so and offer to retry without `-q` (many adult releases omit the resolution from the title). Header line: `**<query>** · 18+ · <quality>`; 版本 per row = the release code if present, else a short cleaned title. Never use adult mode unless the user asked for it. **Hard rule:** refuse any query that refers to minors (teen-age framing, school-age, "loli"/"shota", ages under 18, etc.), and silently drop any result whose title does; no exceptions. Keep the table to release code / short neutral label, size, seeders — never write out explicit descriptions.

## Steps

1. **Resolve the search phrase.**
   - IMDb ID → look up title, year and type:
     ```bash
     curl -s "https://v2.sg.media-imdb.com/suggestion/t/<tt id>.json" | python -c "import sys,json;d=json.load(sys.stdin)['d'][0];print(d['l'],'|',d.get('y'),'|',d.get('q'))"
     ```
   - Title not in English (e.g. 星球大战 / 奥本海默) → use the official English release title.
   - Also decide the film's **original language** (ISO 639-1: `en`, `ja`, `ko`, `zh`, `fr`…) for `--lang`, and its **titles** for `--title`: the official English title plus the original/romanized one when releases commonly use it (君の名は。 → `--title "Your Name" --title "Kimi no Na wa"`; Star Wars → `--title "Star Wars: Episode IV - A New Hope"`). The CLI keeps a release only if its parsed title is ≥85% similar to the phrase or one of these, so spin-offs and localized (dubbed) titles drop out.
   - Build the phrase: lowercase, drop punctuation and parts releases usually omit ("Star Wars: Episode IV - A New Hope" → `star wars a new hope`). Trackers AND the words, so keep it short. For a **movie**, append the year (`dune 2021`) — it separates remakes; if the IMDb lookup gave no year, skip it. For a **TV series**, don't append the year; append `S01E02`-style tags only if the user asked for a specific episode/season.

2. **Services start and stop themselves.** Each CLI run starts Jackett and FlareSolverr (if configured; folders live in `{SKILL_DIR}/config.json`) hidden if they are down and closes them (with Chrome children) when it exits, so every search pays ~15–30s startup. Never ask the user to launch anything; if it exits with `did not come up`, report that line.

3. **Search.** The CLI parses every title with PTT, keeps movies+TV only, same title (±1 year, matching season/episode), drops dead torrents, CAM/TS, upscaled (incl. known regrade groups like iris2), 3D and BR-DISK (BDMV/ISO), drops hardsubbed and foreign-dub-only releases (`--clean` + `--lang`; Dual/Multi audio stays), de-duplicates across trackers, ranks healthy swarms (≥5 seeders) first, then resolution → source (Remux > BluRay > WEB-DL > WEBRip) → seeders, caps each resolution at half of `-n` for `1080p+`, adds a `Parsed` field (resolution, quality, codec, hdr, audio, group, languages…), and (`--magnet`) converts every result to a magnet link — Jackett's `127.0.0.1` download links die when the CLI stops Jackett after the search:
   ```bash
   python "{SKILL_DIR}/jackett_cli.py" search "<phrase>" -c 2000,5000 -q <1080p+|4k|1080p> --clean --lang <xx> --title "<English title>" [--title "<original title>"] --magnet -n 10 --json
   ```
   Adult mode: `search "<phrase>" -c 6000 -q <quality> --words --magnet -n 10 --json` (no `--clean`).
   Takes ~15–60s. Per-indexer errors on stderr are normal; ignore them unless there are zero results. Zero results with the year → retry once without the year (and say so). Few results for a non-English film → also try the original/romanized title as the phrase and merge.

4. **Sanity-check what the CLI kept** (it already removes wrong titles, CAM, upscales, 3D, BR-DISK, hardsubs, dub-only): drop rows with no magnet, and any obvious miss the parser let through. Build 版本 from `Parsed` (group, quality, codec, HDR, audio, Dual Audio). Never show `127.0.0.1` links.

5. **Reply in Chinese, exactly this shape** (the user approved it — no extra sections, no how-to, no filtering disclaimers):

   **<English title> (<year>)**<, tt id if given> · <quality label, e.g. 4K / 1080p+>

   | # | 版本 | 大小 | 做种 |
   |---|---|---|---|
   | 1 | YTS 2160p BluRay 5.1 | 5.7 GB | 286 |
   | 2 | Hybrid Remux DoVi（画质最好） | 49.0 GB | 178 |

   - 版本 = short release description: source group if notable + key tech (Remux / BluRay / WEB, codec, HDR/DV, audio). Omit the film name. Mark the best-quality row with （画质最好）.
   - Magnets in **one** code block, one per line, shortened to the infohash only (lowercase):
     ```
     1  magnet:?xt=urn:btih:<40-hex infohash>
     2  magnet:?xt=urn:btih:<40-hex infohash>
     ```
   - One line of recommendation (e.g. "想要画质好又不想太大，选第 3 或第 6 个（约 11GB，带 HDR）。").
   - Only if rows were dropped in step 4: one line saying which kind and why (e.g. "另有 1 条意大利语片名的版本，可能是意大利语配音，已略过。").
   - Last line: `回复编号开始下载（可多选，如 3 或 3,6）。`

   Then **stop and wait** for the user's pick. Keep the search JSON (full `MagnetUri`s) for step 6.

6. **Send the picked rows to the torrent client** (only after the user replies with numbers).
   - Use the **full** `MagnetUri` from the search JSON (its trackers help the client find peers faster), not the shortened one shown; one argument per pick:
     ```bash
     python "{SKILL_DIR}/download.py" "<magnet>" ["<magnet>" ...]
     ```
     It launches the client set in `{SKILL_DIR}/config.json` once per magnet (or the system's default magnet app if none is set); the client saves into its own default folder. It prints `sent <magnet start>` per item.
   - **Subtitles (not in 18+ mode)**: right after sending, fetch the best Chinese subtitle for each picked row:
     ```bash
     python "{SKILL_DIR}/subhd_cli.py" find "<Chinese title, or original title>" --year <year>
     python "{SKILL_DIR}/subhd_cli.py" get <id> --release "<the picked torrent's full Title>" --dest "{SUBTITLE_DIR}/<folder>"
     ```
     `<folder>` = `<Title (Year)>` for a movie (e.g. `Your Name (2016)`), `<Show (Year)>/Season NN` for TV.
     `find` lists SubHD entries (`/d/` id = Douban id; names are "中文名 原名 (year)", TV is per season, e.g. "行尸走肉 第一季 The Walking Dead (2010)") — pick the one matching title + year (+ season). `get` ranks: season-pack subtitle first for a season-pack torrent > same source family as the torrent (BluRay vs WEB timing) > 精选推荐/官方/原创翻译/AI校对 > 双语 > 简体 > 繁体 > same release group > downloads; drops non-Chinese and image (SUP) subs; for an episode torrent keeps only that episode or season packs; unzips 7z/zip/rar with bsdtar (zip names read as GBK). Several episodes → one `get` per episode into the same `Season NN` folder. If it exits `SubHD refused the download` (verification asked), say so — never try to get around it. No Chinese subtitle → say so in one line.
   - Reply in one or two lines: which rows were sent to the client, then the subtitle folder under `{SUBTITLE_DIR}/…`.
