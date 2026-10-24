"""Build the PyPI package: the frontend first (Node.js 22), copied into
marketmyna/web so the installed app needs no Node.js, then the sdist and
wheel into dist/.

    python .github/build_package.py        # needs: pip install build
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
WEB = ROOT / "marketmyna" / "web"


def main() -> None:
    npm = shutil.which("npm")  # npm.cmd on Windows
    if npm is None:
        sys.exit("Node.js 22 (npm) is needed to build the frontend.")
    for args in (["ci"], ["run", "build"]):
        subprocess.run([npm, *args], cwd=FRONTEND, check=True)
    shutil.rmtree(WEB, ignore_errors=True)
    shutil.copytree(FRONTEND / "dist", WEB)
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    subprocess.run([sys.executable, "-m", "build", "--outdir", str(ROOT / "dist")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
