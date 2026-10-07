"""PikPak helper for /torrent: offline-download magnets into a drive folder under clean names.

  python pikpak_cli.py login        # prompts (or PIKPAK_USER / PIKPAK_PASS env); stores tokens, never the password
  python pikpak_cli.py add "/Movies/Dune (2021)" -m "Dune (2021)" "magnet:?xt=..." [-m NAME MAGNET ...] [--wait 120]
"""
import argparse, asyncio, getpass, json, os, re, sys, time
from pathlib import Path
from pikpakapi import PikPakApi, PikpakException

SESSION = Path.home() / ".pikpak_session.json"


def clean(name):
    """Windows-safe file name: 'Star Wars: A New Hope' -> 'Star Wars - A New Hope'."""
    return re.sub(r'[<>"/\\|?*]', "", name.replace(":", " -")).strip(" .")


async def save(c, **_):
    c.encode_token()  # from_dict needs encoded_token when there is no password
    d = c.to_dict()
    d.pop("password", None); d.pop("_path_id_cache", None)  # cache goes stale if folders are deleted in the app
    SESSION.write_text(json.dumps(d))


def client():
    if not SESSION.exists():
        sys.exit(f"Not logged in: run `python {__file__} login` in a terminal first")
    c = PikPakApi.from_dict(json.loads(SESSION.read_text()))
    c.token_refresh_callback, c.token_refresh_callback_kwargs = save, {}
    return c


async def cmd_login(a):
    user = (os.environ.get("PIKPAK_USER") or input("PikPak email / phone: ")).strip()
    if user.isdigit():  # server reads bare digits as +86 and then rejects the mismatch; other countries: type +65...
        user = "+86" + user
    c = PikPakApi(username=user, password=os.environ.get("PIKPAK_PASS") or getpass.getpass("Password: "))
    await c.login()
    await save(c)
    print("Logged in; session saved to", SESSION)


async def cmd_add(a):
    c = client()
    path = "/" + "/".join(clean(p) for p in a.dir.split("/") if p.strip())
    folder = (await c.path_to_id(path, create=True))[-1]["id"]
    tasks = []  # [name, task]
    for name, magnet in a.m:
        r = await c.offline_download(magnet, parent_id=folder)
        tasks.append([clean(name), r["task"]])
    pending, deadline = list(tasks), time.time() + a.wait
    while pending:  # rename once PikPak has resolved the torrent's top-level file/folder
        for t in list(pending):
            name, task = t
            try:
                info = await c.offline_file_info(task["file_id"]) if task.get("file_id") else {}
            except PikpakException:
                info = {}
            if info.get("name") and info.get("kind"):
                ext = "" if info["kind"] == "drive#folder" else os.path.splitext(info["name"])[1]
                await c.file_rename(task["file_id"], name + ext)
                t.append(name + ext); pending.remove(t)
        if not pending or time.time() > deadline:
            break
        await asyncio.sleep(5)
        live = {x["id"]: x for x in (await c.offline_list()).get("tasks", [])}
        for t in pending:  # file_id is filled in once the magnet's metadata resolves
            t[1] = {**t[1], **live.get(t[1]["id"], {})}
    print(json.dumps({"folder": path, "items": [
        {"name": t[2] if len(t) > 2 else None, "wanted": t[0], "phase": t[1].get("phase"),
         "original": t[1].get("file_name")} for t in tasks]}, ensure_ascii=False, indent=1))
    await save(c)


def main():
    p = argparse.ArgumentParser(description="PikPak CLI for /torrent")
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("login").set_defaults(f=cmd_login)
    ad = s.add_parser("add"); ad.set_defaults(f=cmd_add)
    ad.add_argument("dir", help="drive folder path, created if missing, e.g. '/Movies/Dune (2021)'")
    ad.add_argument("-m", nargs=2, action="append", required=True, metavar=("NAME", "MAGNET"),
                    help="clean name (no extension) + magnet; repeat per item")
    ad.add_argument("--wait", type=int, default=120, help="seconds to wait for metadata before giving up renaming")
    a = p.parse_args()
    asyncio.run(a.f(a))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
