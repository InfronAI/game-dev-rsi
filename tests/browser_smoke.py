"""Exercise the real browser entry point using a disposable headless Chrome profile."""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chrome", default=os.environ.get("CHROME_BIN") or shutil.which("google-chrome") or shutil.which("chromium"))
    p.add_argument("--game", type=Path, default=ROOT/"cases/relay-vault/assets/reference/index.html")
    p.add_argument("--replay", type=Path, help="A recorded HTML replay inside the checkout")
    args = p.parse_args()
    if not args.chrome:
        p.error("Supply --chrome /path/to/chrome or set CHROME_BIN")
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1",0), handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            targets = [("game", args.game)] + ([("replay",args.replay)] if args.replay else [])
            for mode,path in targets:
                relative = path.resolve().relative_to(ROOT)
                url = f"http://127.0.0.1:{server.server_port}/tests/browser-smoke.html?" + urlencode({"target":"/"+relative.as_posix(),"mode":mode})
                with tempfile.TemporaryDirectory() as profile:
                    proc = subprocess.run([args.chrome,"--headless","--disable-gpu","--no-first-run",
                        "--disable-background-networking","--user-data-dir="+profile,"--virtual-time-budget=4000",
                        "--dump-dom",url],capture_output=True,text=True,timeout=30)
                if proc.returncode or '<output id="receipt">passed</output>' not in proc.stdout:
                    raise RuntimeError(f"{mode} browser test failed: {proc.stdout[:700]} {proc.stderr[-500:]}")
                print(f"Passed browser {mode}: {relative}")
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
