#!/usr/bin/env python
"""Install the /torrent skill for Claude Code.

  python install.py --jackett "C:/Jackett"            # the folder holding JackettConsole.exe (or `jackett` on Linux/macOS)
      [--flaresolverr "C:/flaresolverr"]              # optional; default: a `flaresolverr` folder next to Jackett's
      [--client "C:/Program Files/qBittorrent/qbittorrent.exe"]   # optional; default: the OS magnet handler
      [--subs "~/Videos"]                             # where Chinese subtitles are saved
      [--assrt-token TOKEN]                           # optional; free assrt.net API token for extra subtitles
      [--target "~/.claude/skills/torrent"]           # where the skill goes
      [--no-pip]

Re-run any time to change a path; it overwrites the installed copy.
"""
import argparse, json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "skills", "torrent")


def find_exe(folder, *names):
    return next((os.path.join(folder, n) for n in names if os.path.isfile(os.path.join(folder, n))), None)


def main():
    p = argparse.ArgumentParser(description="Install the /torrent skill")
    p.add_argument("--jackett", help="Jackett install folder (prompted if omitted)")
    p.add_argument("--flaresolverr", help="FlareSolverr folder (optional)")
    p.add_argument("--client", help="torrent client executable (optional; default: the OS magnet handler)")
    p.add_argument("--subs", default="~/Videos", help="subtitle download folder")
    p.add_argument("--assrt-token", help="assrt.net API token (optional; kept from the previous install if omitted)")
    p.add_argument("--target", default="~/.claude/skills/torrent", help="skill install folder")
    p.add_argument("--no-pip", action="store_true", help="skip installing Python packages")
    a = p.parse_args()

    jackett = os.path.abspath(os.path.expanduser(a.jackett or input("Jackett install folder: ").strip().strip('"')))
    if not find_exe(jackett, "JackettConsole.exe", "jackett"):
        sys.exit(f"No JackettConsole.exe / jackett in {jackett}: pass the folder Jackett was unpacked into")
    flare = a.flaresolverr or os.path.join(os.path.dirname(jackett), "flaresolverr")
    flare = os.path.abspath(os.path.expanduser(flare))
    if not find_exe(flare, "flaresolverr.exe", "flaresolverr"):
        if a.flaresolverr:
            sys.exit(f"No flaresolverr executable in {flare}")
        print("FlareSolverr not found; Cloudflare-protected indexers may fail (optional, see README)")
        flare = None
    client = a.client and os.path.abspath(os.path.expanduser(a.client.strip('"')))
    if client and (not os.path.isfile(client) or client.lower().endswith((".bat", ".cmd"))):
        sys.exit(f"--client must be the client's executable, not a batch file: {client}")
    subs = os.path.abspath(os.path.expanduser(a.subs))
    target = os.path.abspath(os.path.expanduser(a.target))

    if not a.no_pip:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(ROOT, "requirements.txt")], check=True)

    os.makedirs(target, exist_ok=True)
    for f in os.listdir(SRC):
        if f.endswith((".py", ".md")):
            shutil.copy2(os.path.join(SRC, f), target)
    skill = os.path.join(target, "SKILL.md")  # absolute paths so the agent can run the CLIs from any cwd
    text = open(skill, encoding="utf-8").read()
    text = text.replace("{SKILL_DIR}", target.replace("\\", "/")).replace("{SUBTITLE_DIR}", subs.replace("\\", "/"))
    open(skill, "w", encoding="utf-8").write(text)
    cfg_file = os.path.join(target, "config.json")
    old = json.load(open(cfg_file, encoding="utf-8")) if os.path.exists(cfg_file) else {}
    cfg = {**old, "jackett_dir": jackett, "flaresolverr_dir": flare, "client": client,  # keeps logins (acgrip_cookie)
           "assrt_token": a.assrt_token or old.get("assrt_token")}
    json.dump(cfg, open(cfg_file, "w", encoding="utf-8"), indent=1)

    print(f"Installed to {target}; downloads go to {client or 'the default magnet app'}")


if __name__ == "__main__":
    main()
