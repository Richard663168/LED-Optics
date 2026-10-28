"""Isolated worker so a long optical calculation can be cancelled from the UI."""

import json
import sys
from pathlib import Path
from engine import simulate
from dipole import simulate_dipole

if __name__ == "__main__":
    mode, input_path, output_path = sys.argv[1:]
    try:
        config = json.loads(Path(input_path).read_text(encoding="utf-8"))
        data = simulate(config) if mode == "passive" else simulate_dipole(config)
        result = {"ok": True, "data": data}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    Path(output_path).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
