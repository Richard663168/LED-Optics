"""Optical Stack Studio — local / Streamlit Community Cloud entry point.
Run with: python -m streamlit run app.py
"""

from __future__ import annotations
import copy
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from project import (
    COLORS,
    PRESETS,
    config_json,
    fingerprint,
    make_layer,
    parse_csv,
    preset,
    validate_config,
)

BASE = Path(__file__).resolve().parent
st.set_page_config(page_title="Optical Stack Studio", page_icon="🔬", layout="wide")
st.markdown(
    """<style>
.block-container {padding-top:2rem; max-width:1600px;}
h1,h2,h3 {letter-spacing:-.025em;}
[data-testid="stMetric"] {background:white;border:1px solid #dce5dc;border-radius:12px;padding:18px;}
.stack-layer {display:flex;justify-content:space-between;align-items:center;border:2px solid white;
 padding:0 14px;box-sizing:border-box;color:#203c35;font-size:13px;}
.stack-layer span {overflow-wrap:anywhere;}
.stack-caption {text-align:center;font-size:11px;letter-spacing:1.5px;color:#6d8377;margin:12px;}
</style>""",
    unsafe_allow_html=True,
)


def reset_editor():
    """Rotate widget keys without deleting state still needed by callbacks.

    Streamlit retires widgets that are no longer rendered. Manually deleting
    their keys here can trigger missing-key callbacks during the next event.
    Only remove our non-widget table snapshots; leave widget lifecycle to Streamlit.
    """
    st.session_state.rev += 1
    for key in list(st.session_state):
        if key.startswith("table_seed_"):
            del st.session_state[key]


def replace_config(cfg):
    st.session_state.cfg = validate_config(cfg)
    st.session_state.selected = st.session_state.cfg["layers"][0]["id"]
    reset_editor()


def active_layer():
    layers = st.session_state.cfg["layers"]
    return next((l for l in layers if l["id"] == st.session_state.selected), layers[0])


def apply_table(key):
    # Streamlit reports cumulative cell edits relative to this editor's baseline.
    layers = st.session_state.cfg["layers"]
    for row, edits in st.session_state.get(key, {}).get("edited_rows", {}).items():
        for field, value in edits.items():
            if field in ("d", "n", "k"):
                value = float(value) if value is not None else 0.0
            if field in ("name", "d", "n", "k", "coherence"):
                layers[int(row)][field] = value


def update_role(key, layer_id):
    # A browser can deliver a queued event for a widget already retired by a
    # structural edit. It must not change a different, newly selected layer.
    if key not in st.session_state:
        return
    layer = next(
        (l for l in st.session_state.cfg["layers"] if l["id"] == layer_id), None
    )
    if layer is None:
        return
    role = st.session_state[key]
    if role == layer["role"]:
        return
    if role in ("emitter", "substrate"):
        for other in st.session_state.cfg["layers"]:
            if other["role"] == role:
                other["role"] = "passive"
    layer["role"] = role
    reset_editor()


def update_color(key, layer_id):
    if key not in st.session_state:
        return
    layer = next(
        (l for l in st.session_state.cfg["layers"] if l["id"] == layer_id), None
    )
    if layer is None:
        return
    if layer["color"] == st.session_state[key]:
        return
    layer["color"] = st.session_state[key]
    reset_editor()


def update_setting(name, key):
    if key in st.session_state:
        st.session_state.cfg["settings"][name] = st.session_state[key]


def number_setting(name, label, container=None, **options):
    target = container or st
    key = f"setting_{name}_{st.session_state.rev}"
    target.number_input(
        label,
        value=float(st.session_state.cfg["settings"][name]),
        key=key,
        on_change=update_setting,
        args=(name, key),
        **options,
    )


def select_setting(name, label, values, labels=None):
    key = f"setting_{name}_{st.session_state.rev}"
    st.selectbox(
        label,
        values,
        index=values.index(st.session_state.cfg["settings"][name]),
        format_func=(lambda v: labels[v]) if labels else str,
        key=key,
        on_change=update_setting,
        args=(name, key),
    )


def editor_action(action, layer_id=None, value=None):
    """Run mutations as callbacks BEFORE rendering, never interrupt a partial UI."""
    try:
        layers = st.session_state.cfg["layers"]
        layer = next((l for l in layers if l["id"] == layer_id), None)
        if (
            action in ("up", "down", "add", "remove", "clear_nk", "apply_nk", "place")
            and layer is None
        ):
            return
        if action in ("up", "down"):
            i = layers.index(layer)
            j = i + (-1 if action == "up" else 1)
            if 0 <= j < len(layers):
                layers[i], layers[j] = layers[j], layers[i]
                st.session_state.selected = layer_id
        elif action == "add":
            if len(layers) >= 60:
                raise ValueError("Maximum 60 layers.")
            new = make_layer(color=COLORS[len(layers) % len(COLORS)])
            layers.insert(layers.index(layer) + 1, new)
            st.session_state.selected = new["id"]
        elif action == "remove":
            if len(layers) <= 1:
                return
            i = layers.index(layer)
            layers.pop(i)
            st.session_state.selected = layers[min(i, len(layers) - 1)]["id"]
        elif action == "place":
            emitters = [l for l in layers if l["role"] == "emitter"]
            if len(emitters) != 1 or layer["role"] != "passive":
                raise ValueError(
                    "Select a passive film and assign exactly one emitter first."
                )
            layers.remove(layer)
            ei = layers.index(emitters[0])
            layers.insert(ei + (1 if value == "Electron side" else 0), layer)
            st.session_state.selected = layer_id
        elif action == "clear_nk":
            layer["data"] = None
        elif action in ("apply_nk", "apply_el", "load"):
            upload = st.session_state.get(value)
            if upload is None:
                raise ValueError("Choose a file first.")
            if action == "load":
                if upload.size > 5_000_000:
                    raise ValueError("Use a configuration under 5 MB.")
                replace_config(json.loads(upload.getvalue().decode("utf-8-sig")))
            else:
                rows = parse_csv(upload.getvalue(), 3 if action == "apply_nk" else 2)
                if action == "apply_nk":
                    layer["data"] = rows
                else:
                    if len(rows) > 201:
                        raise ValueError(
                            "Resample to at most 201 points before upload."
                        )
                    st.session_state.cfg["el"] = rows
        elif action == "clear_el":
            st.session_state.cfg["el"] = None
        elif action == "preset":
            replace_config(preset(value))
        else:
            raise ValueError("Unknown editor action.")
        st.session_state.view_error = None
        if action not in ("load", "preset"):
            reset_editor()
    except Exception as exc:
        st.session_state.view_error = str(exc)


def begin_job(mode):
    cfg = validate_config(st.session_state.cfg)
    if mode == "dipole" and cfg.get("el") and len(cfg["el"]) > 201:
        raise ValueError("Use at most 201 emission-spectrum samples.")
    folder = Path(tempfile.mkdtemp(prefix="led_optics_"))
    (folder / "config.json").write_text(config_json(cfg), encoding="utf-8")
    log = (folder / "worker.log").open("w")
    try:
        env = os.environ.copy()
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        process = subprocess.Popen(
            [
                sys.executable,
                str(BASE / "run_job.py"),
                mode,
                str(folder / "config.json"),
                str(folder / "result.json"),
            ],
            cwd=str(BASE),
            stdout=log,
            stderr=log,
            env=env,
        )
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        log.close()
    st.session_state.job = dict(
        mode=mode,
        folder=str(folder),
        process=process,
        config=cfg,
        hash=fingerprint(cfg),
        started=time.monotonic(),
    )
    st.session_state.job_error = None


def stop_job():
    job = st.session_state.job
    if job:
        proc = job["process"]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        shutil.rmtree(job["folder"], ignore_errors=True)
    st.session_state.job = None


@st.fragment(run_every=1)
def job_status():
    job = st.session_state.job
    if not job:
        return
    proc = job["process"]
    folder = Path(job["folder"])
    elapsed = time.monotonic() - job["started"]
    if proc.poll() is None:
        st.info(
            f"Calculating {job['mode']} optics… {elapsed:.0f} s. You can continue editing; this run uses its captured inputs."
        )
        if st.button("Cancel calculation", key="cancel_job"):
            stop_job()
            st.rerun()
        if elapsed > 600:
            stop_job()
            st.session_state.job_error = "Calculation exceeded 10 minutes. Reduce the spectral sample count or check source distances."
            st.rerun()
        return
    try:
        output = folder / "result.json"
        if not output.exists():
            log = (
                (folder / "worker.log").read_text(errors="replace")
                if (folder / "worker.log").exists()
                else ""
            )
            raise ValueError(
                "Calculation process stopped without a result. " + log[-1500:]
            )
        result = json.loads(output.read_text())
        if not result["ok"]:
            raise ValueError(result["error"])
        st.session_state[job["mode"] + "_result"] = {
            **{k: job[k] for k in ("config", "hash")},
            "data": result["data"],
        }
    except Exception as exc:
        st.session_state.job_error = str(exc)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        st.session_state.job = None
    st.rerun()


def launch_calculation(mode):
    try:
        begin_job(mode)
    except Exception as exc:
        st.session_state.job_error = str(exc)


def launch_button(mode, label):
    st.button(
        label,
        type="primary",
        disabled=st.session_state.job is not None,
        key="run_" + mode,
        on_click=launch_calculation,
        args=(mode,),
    )


def plot_lines(df, x, series, ytitle, percent=False):
    fig = go.Figure()
    palette = ["#196b66", "#d3a34b", "#9c6cb0", "#7a9fb1"]
    for i, column in enumerate(series):
        fig.add_trace(
            go.Scatter(
                x=df[x],
                y=df[column],
                name=column,
                mode="lines",
                line=dict(color=palette[i % len(palette)], width=2.5),
            )
        )
    fig.update_layout(
        template="plotly_white",
        height=360,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis_title=x,
        yaxis_title=ytitle,
        legend=dict(orientation="h"),
    )
    if percent:
        fig.update_yaxes(tickformat=".0%")
    return fig


def render_stack(layers, proportional):
    st.markdown(
        '<div class="stack-caption">AIR / GLASS-SIDE EXTRACTION ↑</div>',
        unsafe_allow_html=True,
    )
    total = sum(l["d"] for l in layers if l["role"] != "substrate")
    parts = []
    for layer in layers:
        d = layer["d"]
        height = (
            42
            if layer["role"] == "substrate"
            else (max(28, min(110, 250 * d / max(total, 1))) if proportional else 38)
        )
        label = f"{d/1e6:g} mm" if d >= 10000 else f"{d:g} nm"
        mark = " · EMITTER" if layer["role"] == "emitter" else ""
        border = (
            "outline:2px solid #196b66;outline-offset:-2px;"
            if layer["id"] == st.session_state.selected
            else ""
        )
        parts.append(
            f'<div class="stack-layer" style="height:{height}px;background:{layer["color"]};{border}"><span>{html.escape(layer["name"])}{mark}</span><b>{label}</b></div>'
        )
    st.markdown("".join(parts), unsafe_allow_html=True)
    st.markdown(
        '<div class="stack-caption">TOP ELECTRODE / EXIT MEDIUM ↓</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Thin-film total: {total:g} nm. Optical geometry is planar; view is schematic."
    )


def editor():
    cfg = st.session_state.cfg
    layers = cfg["layers"]
    rev = st.session_state.rev
    left, right = st.columns([2.4, 1])
    with left:
        st.subheader("Layer stack")
        st.caption(
            "Ordered from glass toward the top electrode. Changes update the cross-section immediately. Uploaded n,k override constant n,k fields."
        )
        key = f"table_{rev}"
        seed = f"table_seed_{rev}"
        if seed not in st.session_state:
            st.session_state[seed] = pd.DataFrame(
                [
                    {
                        **{k: l[k] for k in ("name", "d", "n", "k", "coherence")},
                        "role": l["role"],
                        "optical_data": (
                            f"CSV · {len(l['data'])} points"
                            if l.get("data")
                            else "Constants"
                        ),
                    }
                    for l in layers
                ]
            )
        st.data_editor(
            st.session_state[seed],
            key=key,
            hide_index=True,
            width="stretch",
            num_rows="fixed",
            disabled=["role", "optical_data"],
            on_change=apply_table,
            args=(key,),
            column_config={
                "name": st.column_config.TextColumn(
                    "Material", required=True, max_chars=100
                ),
                "d": st.column_config.NumberColumn(
                    "Thickness · nm", min_value=0.001, required=True
                ),
                "n": st.column_config.NumberColumn(
                    "Constant n", min_value=0.0001, required=True
                ),
                "k": st.column_config.NumberColumn(
                    "Constant k", min_value=0.0, required=True
                ),
                "coherence": st.column_config.SelectboxColumn(
                    "Coherence", options=["c", "i"], required=True
                ),
                "role": st.column_config.TextColumn("Role"),
                "optical_data": "Optical data",
            },
        )
        selectkey = f"select_layer_{rev}"
        ids = [l["id"] for l in layers]
        current = (
            st.session_state.selected if st.session_state.selected in ids else ids[0]
        )
        selected = st.selectbox(
            "Selected layer",
            ids,
            index=ids.index(current),
            format_func=lambda id: next(
                f"{i+1}. {l['name']}" for i, l in enumerate(layers) if l["id"] == id
            ),
            key=selectkey,
        )
        st.session_state.selected = selected
        idx = ids.index(selected)
        layer = layers[idx]
        c1, c2, c3, c4 = st.columns(4)
        c1.button(
            "↑ Move up",
            disabled=idx == 0,
            on_click=editor_action,
            args=("up", selected),
        )
        c2.button(
            "↓ Move down",
            disabled=idx == len(layers) - 1,
            on_click=editor_action,
            args=("down", selected),
        )
        c3.button(
            "Remove layer",
            disabled=len(layers) == 1,
            on_click=editor_action,
            args=("remove", selected),
        )
        c4.button(
            "＋ Add layer",
            disabled=len(layers) >= 60,
            on_click=editor_action,
            args=("add", selected),
        )
        st.divider()
        st.markdown(f"**Selected: {layer['name']}**")
        a, b = st.columns(2)
        rolekey = f"field_role_{rev}_{selected}"
        a.selectbox(
            "Layer role",
            ["passive", "emitter", "substrate"],
            index=["passive", "emitter", "substrate"].index(layer["role"]),
            key=rolekey,
            on_change=update_role,
            args=(rolekey, selected),
        )
        colorkey = f"field_color_{rev}_{selected}"
        b.color_picker(
            "Layer color",
            layer["color"],
            key=colorkey,
            on_change=update_color,
            args=(colorkey, selected),
        )
        uploaded = st.file_uploader(
            "Upload n,k CSV for selected layer",
            type=["csv", "txt"],
            key=f"nk_upload_{rev}_{selected}",
            help="Three columns: wavelength_nm,n,k. Comma, semicolon, tab or whitespace separated; optional header.",
        )
        st.button(
            "Apply optical data",
            disabled=uploaded is None,
            on_click=editor_action,
            args=("apply_nk", selected, f"nk_upload_{rev}_{selected}"),
        )
        if layer.get("data"):
            data = layer["data"]
            st.success(
                f"Using {len(data)} optical samples: {data[0][0]:g}–{data[-1][0]:g} nm. No extrapolation."
            )
            st.button(
                "Remove CSV and use constants",
                on_click=editor_action,
                args=("clear_nk", selected),
            )
            with st.expander("Inspect optical constants"):
                df = pd.DataFrame(data, columns=["wavelength_nm", "n", "k"])
                st.plotly_chart(
                    plot_lines(df, "wavelength_nm", ["n", "k"], "Optical constants"),
                    width="stretch",
                )
                st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.caption("Using constant n,k at all wavelengths.")
        with st.expander("Move a 2D layer without changing its optical constants"):
            chosen = st.selectbox(
                "2D layer to move",
                ids,
                format_func=lambda id: next(l["name"] for l in layers if l["id"] == id),
                key=f"move_2d_choice_{rev}",
            )
            side = st.radio(
                "Placement", ["Electron side", "Hole side"], horizontal=True
            )
            st.button(
                "Move next to QD layer",
                on_click=editor_action,
                args=("place", chosen, side),
            )
    with right:
        st.subheader("Live cross-section")
        proportional = st.checkbox("Proportional film thickness", value=False)
        render_stack(layers, proportional)
        st.info(
            "Initial constants are illustrative. Import your exported stack to recover the exact data used in the hosted app."
        )


def passive():
    st.subheader("Passive illumination")
    st.caption(
        "External light enters from the glass side. This is full-stack R/T/A, not LED outcoupling."
    )
    cols = st.columns(4)
    for i, (name, label, options) in enumerate(
        [
            ("start", "Start wavelength · nm", dict(min_value=200.0, max_value=2499.0)),
            ("stop", "Stop wavelength · nm", dict(min_value=201.0, max_value=2500.0)),
            (
                "step",
                "Wavelength step · nm",
                dict(min_value=0.5, max_value=50.0, step=0.5),
            ),
            (
                "angle",
                "Incident angle · degrees",
                dict(min_value=0.0, max_value=84.9, step=1.0),
            ),
        ]
    ):
        number_setting(name, label, cols[i], **options)
    cols = st.columns(3)
    with cols[0]:
        select_setting("pol", "Polarization", ["unpolarized", "s", "p"])
    number_setting(
        "incident", "Glass-side external medium n", cols[1], min_value=0.01, step=0.01
    )
    number_setting("exit", "Top exit medium n", cols[2], min_value=0.01, step=0.01)
    launch_button("passive", "Calculate R / T / A")
    saved = st.session_state.get("passive_result")
    if saved:
        stale = saved["hash"] != fingerprint(st.session_state.cfg)
        if stale:
            st.warning(
                "Inputs changed. The previous result is retained below; recalculate for the current stack."
            )
        with st.expander(
            (
                "Previous result — inputs changed"
                if stale
                else "Calculated passive spectrum"
            ),
            expanded=not stale,
        ):
            df = pd.DataFrame(saved["data"], columns=["wavelength_nm", "R", "T", "A"])
            st.plotly_chart(
                plot_lines(
                    df,
                    "wavelength_nm",
                    ["R", "T", "A"],
                    "Fraction of incident power",
                    True,
                ),
                width="stretch",
            )
            st.download_button(
                "Export passive CSV",
                df.to_csv(index=False),
                "passive_spectrum.csv",
                "text/csv",
            )
            st.download_button(
                "Export passive result + captured inputs",
                config_json({"config": saved["config"], "spectrum": saved["data"]}),
                "passive_results.json",
                "application/json",
            )
            st.dataframe(df, hide_index=True, width="stretch")


def dipoles():
    st.subheader("Dipole emission")
    st.caption(
        "Internal emission, mirror interference, evanescent coupling, glass–air escape and repeated substrate reflections."
    )
    st.info(
        "Transparent QD source host: source-layer k is set to zero only in the dipole solver. Other layers retain their absorption. Isotropic planar approximation; no emitter self-absorption or photon recycling."
    )
    a, b, c = st.columns(3)
    number_setting(
        "horizontal",
        "Horizontal dipole fraction",
        a,
        min_value=0.0,
        max_value=1.0,
        step=0.01,
    )
    number_setting(
        "position",
        "Source position · fraction from glass side",
        b,
        min_value=0.001,
        max_value=0.999,
        step=0.05,
    )
    number_setting(
        "emission",
        "Reference emission wavelength · nm",
        c,
        min_value=200.0,
        max_value=2500.0,
        step=1.0,
    )
    a, b = st.columns(2)
    with a:
        select_setting(
            "distribution",
            "Emission depth distribution",
            ["midpoint", "uniform"],
            {
                "midpoint": "Single source plane",
                "uniform": "Uniform within inset boundaries",
            },
        )
    number_setting(
        "inset", "Uniform-depth interface inset · nm", b, min_value=0.001, step=0.1
    )
    st.caption(
        "Horizontal fraction 2/3 is isotropic. Position 0.5 is the QD midpoint. Uniform depth excludes the inset at each QD interface; test its sensitivity."
    )
    rev = st.session_state.rev
    el = st.file_uploader(
        "Optional emission spectrum CSV",
        type=["csv", "txt"],
        key=f"el_upload_{rev}",
        help="wavelength_nm,intensity; up to 201 points. Interpret as intrinsic source strengths, not already cavity-filtered EL.",
    )
    a, b = st.columns(2)
    a.button(
        "Apply emission spectrum",
        disabled=el is None,
        on_click=editor_action,
        args=("apply_el", None, f"el_upload_{rev}"),
    )
    b.button(
        "Use reference wavelength only", on_click=editor_action, args=("clear_el",)
    )
    spectrum = st.session_state.cfg.get("el")
    st.caption(
        f"{len(spectrum)} spectral samples loaded."
        if spectrum
        else "No spectrum loaded; calculation uses the reference wavelength."
    )
    launch_button("dipole", "Calculate dipole emission")
    saved = st.session_state.get("dipole_result")
    if saved:
        stale = saved["hash"] != fingerprint(st.session_state.cfg)
        if stale:
            st.warning(
                "Inputs changed. These are previous results; recalculate for the current stack."
            )
        with st.expander(
            (
                "Previous result — inputs changed"
                if stale
                else "Calculated dipole emission"
            ),
            expanded=not stale,
        ):
            r = saved["data"]
            s = r["summary"]
            a, b, c = st.columns(3)
            a.metric("Escapes through glass to air", f"{100*s['eta_air']:.2f}%")
            b.metric("Enters the glass", f"{100*s['eta_glass']:.2f}%")
            c.metric("Total power / bulk host", f"{s['total']:.3f}×")
            left, right = st.columns(2)
            with left:
                labels = [
                    "Air escape through glass",
                    "Glass: trapped or subsequently lost",
                    "Film loss / guided modes",
                    "Top-side escape",
                ]
                values = [
                    s[k]
                    for k in [
                        "eta_air",
                        "eta_substrate_unescaped",
                        "eta_film_loss_guided",
                        "eta_top",
                    ]
                ]
                fig = go.Figure(
                    go.Bar(
                        x=values,
                        y=labels,
                        orientation="h",
                        marker_color=["#196b66", "#d3a34b", "#9c6cb0", "#7a9fb1"],
                        text=[f"{v:.2%}" for v in values],
                        textposition="auto",
                    )
                )
                fig.update_layout(
                    title="Power destinations",
                    template="plotly_white",
                    height=370,
                    margin=dict(l=0, r=15, t=45, b=20),
                    yaxis=dict(autorange="reversed"),
                    xaxis=dict(
                        tickformat=".0%", title="Fraction of total dipole power"
                    ),
                )
                st.plotly_chart(fig, width="stretch")
            with right:
                angular = pd.DataFrame(
                    r["angular"],
                    columns=["external_angle_deg", "P_air_per_sr_bulk_normalized"],
                )
                angular["Normalized radiance"] = angular.iloc[:, 1] / max(
                    angular.iloc[:, 1].max(), 1e-30
                )
                st.plotly_chart(
                    plot_lines(
                        angular,
                        "external_angle_deg",
                        ["Normalized radiance"],
                        "Relative power per solid angle",
                    ),
                    width="stretch",
                )
                st.caption(
                    f"Angular distribution at {r['angular_wavelength_nm']:g} nm. 0° is normal to glass."
                )
            for warning in r["warnings"]:
                st.warning(warning)
            st.caption(
                f"Largest integration change: {r['integration_change']*100:.4g}% of total power. Grid agreement is not a material-uncertainty estimate."
            )
            df = pd.DataFrame(r["spectrum"])
            df["eta_air"] = df["air"] / df["total"]
            df["eta_glass"] = df["glass"] / df["total"]
            a, b, c = st.columns(3)
            a.download_button(
                "Export dipole JSON",
                config_json({"config": saved["config"], **r}),
                "dipole_results.json",
                "application/json",
            )
            b.download_button(
                "Export dipole CSV",
                df.to_csv(index=False),
                "dipole_spectrum.csv",
                "text/csv",
            )
            c.download_button(
                "Export angular CSV",
                angular.iloc[:, :2].to_csv(index=False),
                "dipole_angular.csv",
                "text/csv",
            )
            with st.expander("Numerical results"):
                st.dataframe(df, hide_index=True, width="stretch")


def sidebar_import():
    with st.sidebar:
        st.header("Project")
        upload = st.file_uploader(
            "Open stack JSON",
            type=["json"],
            key="stack_import",
            help="Also accepts a dipole results JSON containing a config object.",
        )
        st.button(
            "Load uploaded stack",
            disabled=upload is None,
            on_click=editor_action,
            args=("load", None, "stack_import"),
        )
        st.divider()
        kind = st.selectbox(
            "Illustrative preset",
            list(PRESETS),
            format_func=PRESETS.get,
            key="preset_choice",
        )
        confirm = st.checkbox(
            "Replace current stack and its material data", key="confirm_preset"
        )
        st.button(
            "Load preset",
            disabled=not confirm,
            on_click=editor_action,
            args=("preset", None, kind),
        )
        st.caption(
            "Presets contain illustrative constants, not measured material data. Use the move-layer control to preserve your uploaded n,k."
        )
        st.divider()
        st.caption(
            "Inputs persist during this session. Export a JSON before closing or refreshing. In Cloud, uploads are processed on the hosting server; local runs stay on your computer."
        )


if "cfg" not in st.session_state:
    st.session_state.cfg = preset()
    st.session_state.rev = 0
    st.session_state.selected = st.session_state.cfg["layers"][4]["id"]
    st.session_state.job = None
    st.session_state.job_error = None

sidebar_import()
st.caption("RICHARD LI · MULTILAYER LED OPTICS")
st.title("Optical Stack Studio")
st.write(
    "Build the stack. Understand the light. Local Python calculations with the same hosted-app solvers."
)
if st.session_state.job is not None:
    job_status()
if st.session_state.get("view_error"):
    st.error(st.session_state.view_error)
if st.session_state.job_error:
    st.error(st.session_state.job_error)
tabs = st.tabs(
    ["Stack editor", "Passive optics", "Dipole emission", "Model & local files"]
)
with tabs[0]:
    editor()
with tabs[1]:
    passive()
with tabs[2]:
    dipoles()
with tabs[3]:
    st.subheader("Model assumptions")
    st.markdown("""
- Passive: Python **tmm 0.2.0**; glass incoherent, thin films coherent by default.
- Dipoles: independent recursive Fresnel response and Green-function angular-spectrum integration.
- Exactly one incoherent glass substrate first; one transparent emitter host; other films coherent and isotropic.
- Glass attenuation and repeated incoherent back-surface reflections are included; strongly absorbing substrates are outside the approximation.
- No finite pad edges, roughness, scattering, chirality discrimination, intrinsic nonradiative recombination or photon recycling.
- Total electromagnetic power includes coupling to dissipative channels. Outcoupling is not EQE.
- Uniform-source averaging excludes the chosen inset; source-depth and quadrature sensitivity matter.
- Optical tables are linearly interpolated; there is no extrapolation.
""")
    for filename in ["engine.py", "dipole.py", "MODEL.md"]:
        st.download_button(
            "Download " + filename,
            (BASE / filename).read_bytes(),
            filename,
            key="file_" + filename,
        )
    st.caption(
        "No runtime CDN or external API is needed. After installing requirements, local calculation and plotting work offline."
    )
with st.sidebar:
    st.download_button(
        "Export current stack JSON",
        config_json(st.session_state.cfg),
        "stack.json",
        "application/json",
        type="primary",
    )
    st.caption(
        "Default glass: 1.1 mm. Default ITO: 100 nm. Full compatibility with version 1 hosted-app stack exports."
    )
