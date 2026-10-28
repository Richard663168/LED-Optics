"""Isotropic planar electric dipoles; lossless emitter host, exp(-i omega t).
Fields use tangential-E admittances: Ys=w, Yp=n**2/w, w=kz/k0.
Green-function cavity factors and angular-spectrum Poynting flux are integrated
in q=k_parallel/k0. All powers normalized to a dipole in infinite emitter host.
References: Chance/Prock/Silbey; Lukosz & Kunz JOSA 67,1607 (1977);
Benisty et al JOSA A 15,1192 (1998); Neyts AO 39,3968 (2000).
"""

import json
import numpy as np
from functools import lru_cache


@lru_cache(maxsize=8)
def gauss(order):
    return np.polynomial.legendre.leggauss(order)


def nk_at(layer, wl):
    if layer.get("data"):
        a = np.asarray(layer["data"], float)
        if not a[0, 0] <= wl <= a[-1, 0]:
            raise ValueError(
                layer["name"] + ": optical data do not cover " + str(wl) + " nm."
            )
        return complex(np.interp(wl, a[:, 0], a[:, 1]), np.interp(wl, a[:, 0], a[:, 2]))
    return complex(float(layer["n"]), float(layer["k"]))


def normal(n, q):
    return np.sqrt(complex(n) ** 2 - q * q + 0j)


def rt(ns, ds, q, wl, pol):
    """Stable recursive field r,t from first to last semi-infinite medium."""
    w = [normal(n, q) for n in ns]
    y = w if pol == "s" else [n * n / wi for n, wi in zip(ns, w)]
    r = (y[-2] - y[-1]) / (y[-2] + y[-1])
    t = 2 * y[-2] / (y[-2] + y[-1])
    for j in range(len(ns) - 3, -1, -1):
        r0 = (y[j] - y[j + 1]) / (y[j] + y[j + 1])
        t0 = 1 + r0
        phase = np.exp(2j * np.pi / wl * w[j + 1] * ds[j + 1])
        den = 1 + r0 * r * phase**2
        t = t0 * t * phase / den
        r = (r0 + r * phase**2) / den
    return r, t


def grid(ne, ng, na, nt, ns, qmax, order):
    # Split light lines; quadratic mapping removes integrable 1/sqrt singularities.
    edges = sorted(
        set(
            [0.0, qmax]
            + [
                float(x)
                for x in [ne, ng, na, nt] + [n.real for n in ns]
                if 0 < x < qmax
            ]
        )
    )
    gx, gw = gauss(order)
    u = (gx + 1) / 2
    uw = gw / 2
    qs = []
    ws = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        # sin^2 maps BOTH endpoints quadratically, including internal light lines.
        qs.append(lo + (hi - lo) * np.sin(np.pi * u / 2) ** 2)
        ws.append(uw * (hi - lo) * np.pi / 2 * np.sin(np.pi * u))
    return np.concatenate(qs), np.concatenate(ws)


def prepared(config, wl):
    layers = config["layers"]
    settings = config["settings"]
    em = [i for i, l in enumerate(layers) if l["role"] == "emitter"]
    sub = [i for i, l in enumerate(layers) if l["role"] == "substrate"]
    if len(em) != 1 or sub != [0] or em[0] == 0:
        raise ValueError(
            "Dipole model requires exactly one emitter and one glass substrate, first in the stack."
        )
    e = em[0]
    if layers[0]["coherence"] != "i" or any(l["coherence"] != "c" for l in layers[1:]):
        raise ValueError(
            "Use incoherent glass and coherent films for the dipole model."
        )
    ns = [nk_at(l, wl) for l in layers]
    ds = [float(l["d"]) for l in layers]
    if any(n.real <= 0 or n.imag < 0 for n in ns) or any(d <= 0 for d in ds):
        raise ValueError("Use positive thickness/n and nonnegative k.")
    source_k = ns[e].imag
    ns[e] = complex(ns[e].real)
    ng = ns[0].real
    ne = ns[e].real
    na = float(settings["incident"])
    nt = float(settings["exit"])
    if min(na, nt) <= 0:
        raise ValueError("Boundary indices must be positive.")
    d = ds[e]
    f = float(settings["horizontal"])
    z = float(settings["position"]) * d
    if not 0 <= f <= 1:
        raise ValueError("Horizontal fraction must be between zero and one.")
    uniform = settings.get("distribution") == "uniform"
    inset = float(settings.get("inset", 1))
    if uniform:
        if not 0 < inset < d / 2:
            raise ValueError(
                "Depth inset must be positive and less than half the emitter thickness."
            )
    elif not 0 < z < d:
        raise ValueError(
            "Place the source strictly inside the emitter, not on an interface."
        )
    return ns, ds, e, ne, ng, na, nt, source_k, f, z, inset, uniform


def spectral(config, wl, order=96, depth_order=8, angle=False):
    ns, ds, e, ne, ng, na, nt, source_k, f, z, inset, uniform = prepared(config, wl)
    d = ds[e]
    k0 = 2 * np.pi / wl
    if uniform:
        gx, gw = gauss(depth_order)
        zs = inset + (gx + 1) / 2 * (d - 2 * inset)
        zw = gw / 2
    else:
        zs = np.array([z])
        zw = np.array([1.0])
    mind = min(min(zs), d - max(zs))
    qmax = max(12.0, ne + 12 / (k0 * mind))
    left_n = [ns[e]] + list(reversed(ns[1:e])) + [complex(ng)]
    left_d = [0.0] + list(reversed(ds[1:e])) + [0.0]
    right_n = ns[e:] + [complex(nt)]
    right_d = [0.0] + ds[e + 1 :] + [0.0]
    full_n = [complex(ng)] + ns[1:] + [complex(nt)]
    full_d = [0.0] + ds[1:] + [0.0]

    def evaluate(q):
        w = normal(ne, q)
        wg = normal(ng, q)
        wt = normal(nt, q)
        # Material attenuation in macroscopic glass; no coherent back-surface feedback.
        attenuation = np.exp(-2 * k0 * normal(ns[0], q).imag * ds[0])
        total = np.zeros_like(q)
        glass = total.copy()
        air = total.copy()
        top = total.copy()
        for pol in ["s", "p"]:
            rl, tl = rt(left_n, left_d, q, wl, pol)
            rr, tr = rt(right_n, right_d, q, wl, pol)
            rf, _ = rt(full_n, full_d, q, wl, pol)
            ya = normal(na, q) if pol == "s" else na * na / normal(na, q)
            yg = wg if pol == "s" else ng * ng / wg
            yt = wt if pol == "s" else nt * nt / wt
            rga = (yg - ya) / (yg + ya)
            Tga = np.where(
                q < min(ng, na), 4 * np.real(yg) * np.real(ya) / np.abs(yg + ya) ** 2, 0
            )
            escape = (
                Tga
                * attenuation
                / np.maximum(
                    1 - np.abs(rga) ** 2 * np.abs(rf) ** 2 * attenuation**2, 1e-30
                )
            )
            for z, weight in zip(zs, zw):
                a = rl * np.exp(2j * k0 * w * z)
                b = rr * np.exp(2j * k0 * w * (d - z))
                den = 1 - a * b
                Fh = (1 + a) * (1 + b) / den
                if pol == "s":
                    total += weight * f * 3 / 4 * np.real(q / (ne * w) * Fh)
                    cl = weight * f * 3 / 8 * q / ne / np.abs(w) ** 2
                    cr = cl
                    down = (
                        np.abs(tl * np.exp(1j * k0 * w * z) * (1 + b) / den) ** 2
                        * cl
                        * np.real(yg)
                    )
                    up = (
                        np.abs(tr * np.exp(1j * k0 * w * (d - z)) * (1 + a) / den) ** 2
                        * cr
                        * np.real(yt)
                    )
                else:
                    Fv = (1 - a) * (1 - b) / den
                    total += weight * (
                        f * 3 / 4 * np.real(q * w / ne**3 * Fh)
                        + (1 - f) * 3 / 2 * np.real(q**3 / (ne**3 * w) * Fv)
                    )
                    ch = f * 3 / 8 * q * np.abs(w) ** 2 / ne**5
                    cv = (1 - f) * 3 / 4 * q**3 / ne**5
                    down = (
                        weight
                        * np.abs(tl * np.exp(1j * k0 * w * z) / den) ** 2
                        * (ch * np.abs(1 + b) ** 2 + cv * np.abs(1 - b) ** 2)
                        * np.real(yg)
                    )
                    up = (
                        weight
                        * np.abs(tr * np.exp(1j * k0 * w * (d - z)) / den) ** 2
                        * (ch * np.abs(1 + a) ** 2 + cv * np.abs(1 - a) ** 2)
                        * np.real(yt)
                    )
                down = np.where(q < ng, down, 0)
                up = np.where(q < nt, up, 0)
                glass += down
                top += up
                air += down * escape
        return np.array([total, glass, air, top])

    q, weights = grid(ne, ng, na, nt, ns, qmax, order)
    powers = evaluate(q) @ weights
    out = {
        "wavelength_nm": float(wl),
        "total": float(powers[0]),
        "glass": float(powers[1]),
        "air": float(powers[2]),
        "top": float(powers[3]),
        "source_k_ignored": float(source_k),
        "q_max": float(qmax),
    }
    if angle:
        theta = np.linspace(0, 89.9, 181)
        rad = np.deg2rad(theta)
        qa = na * np.sin(rad)
        # Avoid exact q=0 and light lines in field admittances.
        qa[0] = na * 1e-7
        v = evaluate(qa)[2] * na * np.cos(rad)
        # dP/dOmega=(dP/dq)*(dq/dtheta)/(2*pi*sin(theta)). Normalize peak for display.
        radiance = v / (2 * np.pi * np.maximum(np.sin(rad), 1e-7))
        out["angular"] = [[float(t), float(r)] for t, r in zip(theta, radiance)]
    return out


def simulate_dipole(config):
    settings = config["settings"]
    wl = float(settings["emission"])
    if not 200 <= wl <= 2500:
        raise ValueError("Emission wavelength must be within 200–2500 nm.")
    spectrum = config.get("el")
    if spectrum:
        a = np.asarray(spectrum, float)
        if len(a) > 201:
            raise ValueError(
                "Resample EL data to at most 201 points for dipole integration."
            )
        if np.any(a[:, 1] < 0) or np.any(np.diff(a[:, 0]) <= 0):
            raise ValueError(
                "EL intensity must be nonnegative with increasing wavelengths."
            )
        # Trapezoidal spectral weights, normalized before averaging powers.
        sw = np.zeros(len(a))
        delta = np.diff(a[:, 0])
        sw[:-1] += delta / 2
        sw[1:] += delta / 2
        sw *= a[:, 1]
        if sw.sum() <= 0:
            raise ValueError("EL spectrum must have positive integrated intensity.")
        sw /= sw.sum()
        waves = a[:, 0]
    else:
        waves = np.array([wl])
        sw = np.array([1.0])
    rows = []
    warning = []
    worst = 0.0
    for wave in waves:
        low = spectral(config, float(wave), 64, 8)
        high = spectral(config, float(wave), 128, 16)
        keys = ["total", "glass", "air", "top"]
        err = max(abs(high[k] - low[k]) for k in keys) / max(abs(high["total"]), 1e-12)
        if err > 0.005:
            low = high
            high = spectral(config, float(wave), 256, 32)
            err = max(abs(high[k] - low[k]) for k in keys) / max(
                abs(high["total"]), 1e-12
            )
        worst = max(worst, err)
        high["relative_integration_change"] = float(err)
        if high["total"] <= 0 or not np.isfinite(list(high.values())).all():
            raise ValueError(
                "Dipole integration failed; check optical constants and source position."
            )
        if high["glass"] + high["top"] > high["total"] * 1.005:
            warning.append(
                "Power balance failed at "
                + str(wave)
                + " nm; do not interpret this efficiency."
            )
        rows.append(high)
    avg = {
        k: float(sum(w * r[k] for w, r in zip(sw, rows)))
        for k in ["total", "glass", "air", "top"]
    }
    if worst > 0.01:
        warning.append(
            "Integration changed by more than 1%; narrow modes or near-interface sources need further convergence checks."
        )
    if any(r["source_k_ignored"] > 0 for r in rows):
        warning.append(
            "QD host k was set to zero in this dipole calculation; emitter self-absorption/recycling is not included."
        )
    if not any(
        nk_at(l, wl).imag > 1e-9 for l in config["layers"] if l["role"] == "passive"
    ):
        warning.append(
            "A lossless stack can contain unresolved bound-mode poles; efficiencies require additional validation if guiding is present."
        )
    avg["eta_air"] = avg["air"] / avg["total"]
    avg["eta_glass"] = avg["glass"] / avg["total"]
    avg["eta_top"] = avg["top"] / avg["total"]
    avg["eta_film_loss_guided"] = 1 - avg["eta_glass"] - avg["eta_top"]
    avg["eta_substrate_unescaped"] = avg["eta_glass"] - avg["eta_air"]
    angles = spectral(config, wl, 128, 16, True)["angular"]
    return {
        "summary": avg,
        "spectrum": rows,
        "angular": angles,
        "angular_wavelength_nm": wl,
        "integration_change": worst,
        "warnings": list(dict.fromkeys(warning)),
        "assumptions": [
            "Planar isotropic layers; transparent emitter host.",
            "Glass back surface is incoherent; attenuation and multiple intensity reflections included.",
            "Uniform depth averaging excludes the configured inset from each interface.",
            "EL weights represent intrinsic source strengths; powers are averaged before taking ratios.",
            "No intrinsic nonradiative recombination, roughness, scattering, or photon recycling.",
        ],
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("config")
    a = p.parse_args()
    with open(a.config) as f:
        c = json.load(f)
    with open("dipole_results.json", "w") as f:
        json.dump(simulate_dipole(c), f, indent=2)
    print("Saved dipole_results.json")
