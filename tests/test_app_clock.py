"""The API keeps times as naive UTC on every OS (api/app.py pins the
process zone; Windows has no time.tzset). CI runs this on a machine set to
a non-UTC zone (.github/workflows/ci.yml)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECK = (
    "import datetime, api.app\n"
    "local = datetime.datetime.now()\n"
    "utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)\n"
    "print(round((local - utc).total_seconds()))\n"
)


def test_app_clock_is_utc_whatever_the_machine_zone(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "TZ"}
    env["MARKETMYNA_HOME"] = str(tmp_path)
    out = subprocess.run([sys.executable, "-c", CHECK], cwd=ROOT, env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert abs(int(out.stdout.strip().splitlines()[-1])) < 60
