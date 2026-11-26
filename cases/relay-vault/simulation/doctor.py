import json
import shutil
import subprocess

node = shutil.which("node")
version = subprocess.check_output([node, "--version"], text=True).strip() if node else "missing"
ready = bool(node) and int(version.lstrip("v").split(".")[0]) >= 22
print(json.dumps({"checks": [{"name": "Node.js 22+", "ok": ready, "detail": version}]}))
