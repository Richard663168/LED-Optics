import json
import numpy as np
from tmm import inc_tmm


def simulate(config):
    start, stop, step = [
        float(config["settings"][key]) for key in ("start", "stop", "step")
    ]
    angle = float(config["settings"]["angle"])
    if not (200 <= start < stop <= 2500 and 0.5 <= step <= 50 and 0 <= angle < 85):
        raise ValueError(
            "Use 200–2500 nm, increasing bounds, step 0.5–50 nm, and angle 0–85°."
        )
    layers = config["layers"]
    if not layers:
        raise ValueError("Add at least one layer.")

    def index(layer, wavelength):
        data = layer.get("data")
        if data:
            arr = np.array(data, dtype=float)
            if wavelength < arr[0, 0] or wavelength > arr[-1, 0]:
                raise ValueError(
                    layer["name"] + ": optical data do not cover the wavelength range."
                )
            return complex(
                np.interp(wavelength, arr[:, 0], arr[:, 1]),
                np.interp(wavelength, arr[:, 0], arr[:, 2]),
            )
        return complex(float(layer["n"]), float(layer["k"]))

    for layer in layers:
        if float(layer["d"]) <= 0 or float(layer["n"]) <= 0 or float(layer["k"]) < 0:
            raise ValueError("Thickness and n must be positive; k must be nonnegative.")
    waves = np.arange(start, stop + step * 1e-6, step)
    result = []
    for wavelength in waves:
        n = (
            [complex(float(config["settings"]["incident"]))]
            + [index(l, wavelength) for l in layers]
            + [complex(float(config["settings"]["exit"]))]
        )
        if n[0].real <= 0 or n[-1].real <= 0:
            raise ValueError("Boundary indices must be positive.")
        d = [np.inf] + [float(l["d"]) for l in layers] + [np.inf]
        c = ["i"] + [l["coherence"] for l in layers] + ["i"]
        pols = (
            ["s", "p"]
            if config["settings"]["pol"] == "unpolarized"
            else [config["settings"]["pol"]]
        )
        outputs = [inc_tmm(pol, n, d, c, np.deg2rad(angle), wavelength) for pol in pols]
        r = float(np.mean([o["R"] for o in outputs]))
        t = float(np.mean([o["T"] for o in outputs]))
        result.append([float(wavelength), r, t, 1 - r - t])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Passive planar optics using Steve Byrnes’ tmm library."
    )
    parser.add_argument("config", nargs="?", default="stack.json")
    args = parser.parse_args()
    with open(args.config) as f:
        config = json.load(f)
    np.savetxt(
        "passive_spectrum.csv",
        simulate(config),
        delimiter=",",
        header="wavelength_nm,R,T,A",
        comments="",
    )
    print("Saved passive_spectrum.csv")
