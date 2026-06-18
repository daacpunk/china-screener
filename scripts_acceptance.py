"""Standalone acceptance: demo flow + xlsx round-trip (Acceptance #3 and #4)."""
import io
import os
import sys
import tempfile

import openpyxl

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# isolated DB
tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(tmp, "acc.db")
os.environ["APP_SECRET"] = "acc-secret"

from app.db import init_db
from app import demo, settings_store as ss, formula_gen as fg
from app.web.common import run_active_screen

init_db()

# ---- Acceptance #3: load demo, run screen, assert non-empty + |z|-ranked ----
demo.load_demo_data()
res = run_active_screen()
assert not res.get("_empty"), "screen returned empty"
os_n = len(res["oversold"]); ob_n = len(res["overbought"])
print(f"[#3] oversold-reversion={os_n}  overbought-fade={ob_n}")
assert os_n > 0, "oversold list empty"
assert ob_n > 0, "overbought list empty"
for k in ("oversold", "overbought"):
    z = res[k]["abs_z"].tolist()
    assert z == sorted(z, reverse=True), f"{k} not ranked by |z|"
assert (res["master"]["dislocation_type"] == "IDIOSYNCRATIC").any(), "no idiosyncratic example"
print("[#3] both lists non-empty, ranked by |z|, idiosyncratic example present  ✓")

# ---- Acceptance #4: formula generator produces a valid downloadable xlsx ----
d = ss.get_active_dictionary()
tickers = ["BABA-CN", "PDD-CN"]
for method in ("A", "B"):
    data = fg.build_formula_workbook(tickers, d["data"], method=method, lookback=50)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Instructions" in wb.sheetnames
    assert "BABA-CN" in wb.sheetnames
    print(f"[#4] Method {method} xlsx opens; sheets={wb.sheetnames[:4]}...  ✓")

print("\nALL STANDALONE ACCEPTANCE CHECKS PASSED")
