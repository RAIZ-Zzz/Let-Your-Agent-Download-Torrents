"""Hand magnets to your torrent client (`client` in config.json), or to the OS default magnet handler if none is set.

  python download.py "magnet:?xt=urn:btih:..." ["magnet:?xt=..." ...]

The client is launched once per magnet as `<client> <magnet>`, which qBittorrent, uTorrent/BitTorrent, BitComet,
Deluge, Transmission-qt and Tixati all accept; it saves into the client's own default folder.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_CFG_FILE = os.path.join(HERE, "config.json")


def launch(magnets, client=None):
    bad = [m for m in magnets if not m.startswith("magnet:?")]
    if bad:  # also keeps os.startfile from opening anything but a magnet handler
        sys.exit(f"Not a magnet link: {bad[0][:80]}")
    if client and client.lower().endswith((".bat", ".cmd")):  # cmd.exe would run `&cmd` from tracker-supplied names
        sys.exit(f"Point `client` at the program's .exe, not a batch file: {client}")
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
             **({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt" else {"start_new_session": True})}
    for m in magnets:
        if client:
            subprocess.Popen([client, m], **quiet)
        elif os.name == "nt":
            os.startfile(m)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", m], **quiet)
        print("sent", m[:60])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cfg = json.load(open(_CFG_FILE, encoding="utf-8")) if os.path.exists(_CFG_FILE) else {}
    launch(sys.argv[1:], os.environ.get("TORRENT_CLIENT") or cfg.get("client"))
