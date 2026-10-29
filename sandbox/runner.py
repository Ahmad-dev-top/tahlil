"""Executed INSIDE the sandbox. Loads the query result as `df`, runs the agent's code,
and captures charts. The agent's code may print a JSON object with key stats."""
import json
import os
import sys
import traceback

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

WORK = os.environ.get("WORK_DIR", "/work")
OUT = os.path.join(WORK, "out")
os.makedirs(OUT, exist_ok=True)

df = pd.read_csv(os.path.join(WORK, "result.csv"))
code = open(os.path.join(WORK, "analysis.py")).read()

namespace = {"df": df, "pd": pd, "plt": plt, "json": json, "OUT_DIR": OUT}
try:
    exec(compile(code, "analysis.py", "exec"), namespace)
except Exception:
    traceback.print_exc()
    sys.exit(1)

# Save any figures the code left open but did not save.
for i, num in enumerate(plt.get_fignums()):
    path = os.path.join(OUT, f"chart_{i + 1}.png")
    if not os.path.exists(path):
        plt.figure(num).savefig(path, dpi=120, bbox_inches="tight")
