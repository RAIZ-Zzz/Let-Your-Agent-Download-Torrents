# Let Your Agent Download Torrents

A [Claude Code](https://claude.com/claude-code) skill: type `/torrent Dune 2021` and the agent searches your local
[Jackett](https://github.com/Jackett/Jackett), keeps only good releases, shows a short table, and after you pick
sends the magnets to your own torrent client, then fetches Chinese subtitles from [SubHD](https://subhd.me).

What the search keeps:

- **1080p or better** only (`4k` for 2160p only, `best` for a pure quality ranking).
- **Original-language audio**: dub-only and hardcoded-subtitle releases are dropped; Dual/Multi audio stays.
- No CAM/TS, upscales, 3D or raw Blu-ray disc images; dead torrents removed; duplicates across trackers merged.
- Ranked healthy swarms first, then resolution, Remux > BluRay > WEB, Dolby Vision > HDR, lossless audio, seeders.
- Every result becomes a magnet link (Jackett's local download links stop working once it is shut down).

**Anime mode** (`/torrent 葬送的芙莉莲 动漫`, or automatic for Japanese animation): searches by the romanized title,
keeps fansub releases whose Chinese subtitles are a switchable track (`内封`), drops burned-in ones (`内嵌`, plain
`简体` MP4s), and ranks healthy `内封` releases first, so most picks need no separate subtitle at all.

**Subtitles**: [SubHD](https://subhd.me) first; when it has nothing (common for anime), the
[sub_share](https://github.com/foxofice/sub_share) anime archive (no longer updated since Sep 2025) and
[assrt.net](https://assrt.net) (needs a free API token), the [Anime字幕论坛](https://bbs.acgrip.com) (needs an
account: run `python ~/.claude/skills/torrent/subs_cli.py acgrip-login` once in your own terminal), and as a last
resort the Thunder player's subtitle index (no account; kept only when the text is Chinese).
字幕服务由 [assrt.net](https://assrt.net) 提供.

The agent replies in Chinese by default (edit step 5 of `skills/torrent/SKILL.md` to change that).

## Prerequisites

- **Python 3.8+** and **Claude Code**.
- **Jackett** unpacked somewhere, with a few indexers added in its web UI (`http://127.0.0.1:9117`).
  The skill starts Jackett hidden when it is needed and stops it afterwards; you never launch it yourself.
- **FlareSolverr** (optional): needed by Cloudflare-protected indexers such as 1337x.
  Put it in a `flaresolverr` folder next to the Jackett folder, or pass `--flaresolverr`.
- A **torrent client** that accepts a magnet link as its first argument: qBittorrent, uTorrent/BitTorrent, BitComet,
  Deluge, Transmission-qt, Tixati… Optional: without one, magnets go to whatever app your system opens magnet links with.
- Windows is the tested platform. Linux/macOS should work (Jackett data in `~/.config/Jackett`; subtitles need
  `bsdtar`: built in on macOS, `libarchive-tools` on Debian/Ubuntu) but are untested.

## Install

```bash
git clone https://github.com/RAIZ-Zzz/Let-Your-Agent-Download-Torrents.git
cd Let-Your-Agent-Download-Torrents
python install.py --jackett "C:/Jackett" --client "C:/Program Files/qBittorrent/qbittorrent.exe"
```

`--jackett` is the folder that holds `JackettConsole.exe`; `--client` is your torrent client's executable (not a
`.bat`/`.cmd` wrapper). Downloads land in the client's own default folder. `TORRENT_CLIENT=<exe>` overrides it for one run.

Other options: `--flaresolverr <dir>`, `--subs <dir>` (subtitle folder, default `~/Videos`),
`--assrt-token <token>` (register at assrt.net, copy the API token from the user panel; or set `ASSRT_TOKEN`),
`--target <dir>` (default `~/.claude/skills/torrent`), `--no-pip`. Re-run to change any of them.

The installer pip-installs `parsett`, copies the skill to `~/.claude/skills/torrent`, and writes `config.json` there
with your paths.

The Jackett API key is read from Jackett's data folder (`C:\ProgramData\Jackett` or `~/.config/Jackett`).
If yours lives elsewhere, set `JACKETT_API_KEY` (and `JACKETT_PASSWORD` if you set an admin password).

## Use

In Claude Code:

```
/torrent tt1160419                     # by IMDb id
/torrent Dune Part Two 4k             # 4K only
/torrent Ahsoka season 1 best          # top 3 by picture + sound quality
/torrent 葬送的芙莉莲 第二季 动漫        # anime: fansub releases with Chinese soft subs first
```

Reply with the row numbers (e.g. `3` or `1,3`) to start those downloads.

The CLIs also work on their own:

```bash
python ~/.claude/skills/torrent/jackett_cli.py search "dune 2021" -c 2000,5000 -q 1080p+ --clean --magnet -n 10
python ~/.claude/skills/torrent/download.py "magnet:?xt=urn:btih:..."
python ~/.claude/skills/torrent/subhd_cli.py find "沙丘" --year 2021
python ~/.claude/skills/torrent/subs_cli.py share "葬送的芙莉莲" --year 2023
```

Offline self-check: `python skills/torrent/test_cli.py`.

## License

MIT
