"""Configuration and text-file parsing shared by the UI and tests."""

from __future__ import annotations
import copy
import hashlib
import json
import math
import re
import uuid
import numpy as np

COLORS = [
    "#c8ddd8",
    "#dce5d5",
    "#c6d8c0",
    "#dfd7c9",
    "#e8bd91",
    "#d5c0dd",
    "#c2d7dc",
    "#d0dce7",
    "#e5dfc6",
    "#b6c3bd",
]
DEFAULT_SETTINGS = dict(
    start=550.0,
    stop=750.0,
    step=2.0,
    angle=0.0,
    pol="unpolarized",
    incident=1.0,
    exit=1.0,
    horizontal=2 / 3,
    position=0.5,
    emission=640.0,
    distribution="midpoint",
    inset=1.0,
)
PRESETS = {
    "electron": "Electron-side 2D · 10 nm",
    "reference": "QD reference · no 2D",
    "hole30": "Hole-side 2D · 30 nm",
    "hole50": "Hole-side 2D · 50 nm",
}


def make_layer(
    name="New layer",
    d=20.0,
    n=1.7,
    k=0.0,
    role="passive",
    coherence="c",
    color="#d4ddd1",
):
    return dict(
        id=uuid.uuid4().hex,
        name=name,
        d=float(d),
        n=float(n),
        k=float(k),
        role=role,
        coherence=coherence,
        color=color,
        data=None,
    )


def preset(kind="electron"):
    definitions = [
        ("Glass", 1100000, 1.5, 0, "substrate", "i"),
        ("ITO", 100, 1.9, 0.02),
        ("PEDOT:PSS", 45, 1.5, 0.02),
        ("PTAA", 20, 1.7, 0),
        ("CsPbI₃ QDs", 20, 2, 0.02, "emitter"),
        ("Chiral 2D", 10, 2.1, 0.01),
        ("PO-T2T", 20, 1.7, 0),
        ("TPBi", 28, 1.7, 0),
        ("LiF", 1, 1.39, 0),
        ("Al", 100, 1.4, 7.4),
    ]
    layers = [make_layer(*args, color=COLORS[i]) for i, args in enumerate(definitions)]
    if kind == "reference":
        layers.pop(5)
    elif kind in ("hole30", "hole50"):
        film = layers.pop(5)
        film["d"] = 30.0 if kind == "hole30" else 50.0
        layers.insert(4, film)
    return dict(
        version=1,
        preset=kind,
        layers=layers,
        settings=copy.deepcopy(DEFAULT_SETTINGS),
        el=None,
    )


def validate_data(rows, cols, limit=20000):
    a = np.asarray(rows, dtype=float)
    if a.ndim != 2 or a.shape[1] != cols or not 2 <= len(a) <= limit:
        raise ValueError(f"Expected 2–{limit} rows with {cols} columns.")
    if (
        not np.isfinite(a).all()
        or (a[:, 0] <= 0).any()
        or (np.diff(a[:, 0]) <= 0).any()
    ):
        raise ValueError(
            "Use finite numbers and positive, strictly increasing wavelengths; duplicates are not allowed."
        )
    if (a[:, 1] < 0).any() or (
        cols == 3 and ((a[:, 1] <= 0).any() or (a[:, 2] < 0).any())
    ):
        raise ValueError(
            "n must be positive; k and emission intensity must be nonnegative."
        )
    if cols == 2 and np.trapezoid(a[:, 1], a[:, 0]) <= 0:
        raise ValueError("Emission spectrum must have positive integrated intensity.")
    return a.tolist()


def parse_csv(content, cols):
    if len(content) > 3_000_000:
        raise ValueError("Use a file smaller than 3 MB.")
    text = (
        content.decode("utf-8-sig")
        if isinstance(content, bytes)
        else content.lstrip("\ufeff")
    )
    lines = [
        l.strip()
        for l in text.splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]
    rows = []
    for i, line in enumerate(lines):
        parts = re.split(r"[,;\t ]+", line)
        try:
            row = [float(v) for v in parts]
        except ValueError:
            if i == 0 and any(re.search(r"[a-zA-Z]", v) for v in parts):
                continue
            raise ValueError(f"Non-numeric data on line {i+1}.")
        if len(row) != cols:
            raise ValueError(f"Expected {cols} columns on line {i+1}.")
        rows.append(row)
    rows.sort(key=lambda r: r[0])
    return validate_data(rows, cols)


def validate_config(raw):
    c = copy.deepcopy(raw.get("config", raw)) if isinstance(raw, dict) else None
    if (
        not isinstance(c, dict)
        or c.get("version") != 1
        or not isinstance(c.get("layers"), list)
        or not 1 <= len(c["layers"]) <= 60
    ):
        raise ValueError(
            "Expected an Optical Stack Studio version 1 stack with 1–60 layers."
        )
    if not isinstance(c.get("settings"), dict):
        raise ValueError("Missing settings object.")
    ids = set()
    for layer in c["layers"]:
        if not isinstance(layer.get("name"), str) or not 1 <= len(layer["name"]) <= 100:
            raise ValueError("Every layer needs a name of 1–100 characters.")
        for key in ["d", "n", "k"]:
            layer[key] = float(layer[key])
            if not math.isfinite(layer[key]):
                raise ValueError("Layer inputs must be finite.")
        if layer["d"] <= 0 or layer["n"] <= 0 or layer["k"] < 0:
            raise ValueError("Use positive thickness/n and nonnegative k.")
        if layer.get("role") not in ("passive", "emitter", "substrate") or layer.get(
            "coherence"
        ) not in ("c", "i"):
            raise ValueError("Invalid layer role or coherence.")
        identity = layer.get("id")
        if not isinstance(identity, str) or identity in ids:
            identity = uuid.uuid4().hex
        layer["id"] = identity
        ids.add(identity)
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(layer.get("color", ""))):
            layer["color"] = "#d4ddd1"
        if layer.get("data") is not None:
            layer["data"] = validate_data(layer["data"], 3)
    c["settings"] = {**DEFAULT_SETTINGS, **c["settings"]}
    s = c["settings"]
    for key in DEFAULT_SETTINGS:
        if key not in ("pol", "distribution"):
            s[key] = float(s[key])
            if not math.isfinite(s[key]):
                raise ValueError("Settings must be finite.")
    if s["pol"] not in ("s", "p", "unpolarized") or s["distribution"] not in (
        "midpoint",
        "uniform",
    ):
        raise ValueError("Invalid polarization or source distribution.")
    if not (
        200 <= s["start"] < s["stop"] <= 2500
        and 0.5 <= s["step"] <= 50
        and 0 <= s["angle"] < 85
    ):
        raise ValueError("Check the passive wavelength range, step and angle.")
    if not (
        s["incident"] > 0
        and s["exit"] > 0
        and 0 <= s["horizontal"] <= 1
        and 0 < s["position"] < 1
        and 200 <= s["emission"] <= 2500
        and s["inset"] > 0
    ):
        raise ValueError("Check boundary indices and dipole source settings.")
    if c.get("el") is not None:
        c["el"] = validate_data(c["el"], 2, 201)
    c.setdefault("preset", "custom")
    c.setdefault("el", None)
    return c


def config_json(config):
    return json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False)


def fingerprint(config):
    return hashlib.sha256(config_json(config).encode()).hexdigest()
