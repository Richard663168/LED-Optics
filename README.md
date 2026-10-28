# Optical Stack Studio — Streamlit / local Python

A complete editable interface for multilayer LED optics. Run locally from VS Code, or deploy the same repository on Streamlit Community Cloud. The interface is a Streamlit port, not a pixel-for-pixel HTML copy; it uses the same passive and dipole numerical engines.

## Quick start on Richard's Mac

Use Python **3.11 or 3.12**; 3.12 is the tested version. Extract the ZIP, then open the folder containing `app.py` in VS Code. If placing its contents directly in your existing LED Optics folder, back up your own `stack.json` first. This package does not overwrite it (examples have different names).

Open **Terminal → New Terminal**, make sure it is in the folder containing `app.py`, then run:

```bash
cd "/Users/richard/Documents/Visual Studio/LED Optics"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

If the ZIP was extracted into a subfolder, `cd` into that folder instead. VS Code's Explorer should show `app.py` directly beneath the opened folder.

Install Microsoft's Python extension, then use **Command+Shift+P → Python: Select Interpreter → .venv**. Use the terminal command above to launch the UI, not the ordinary Run Python File button. Alternatively, the included `.vscode/launch.json` provides **Run and Debug → Optical Stack Studio (Streamlit)** after selecting the interpreter.

Streamlit prints a Local URL, usually `http://localhost:8501`. Open that URL in your browser. The browser is the interface; Python runs on your Mac. Stop with **Control+C** in the terminal.

Installation requires internet. Once dependencies are installed, local editing, calculations, file uploads and plots work **offline**: no CDN, Pyodide, remote API or API key is used. Streamlit telemetry is disabled by the included configuration.

When returning later:

```bash
cd "/Users/richard/Documents/Visual Studio/LED Optics"
source .venv/bin/activate
python -m streamlit run app.py
```

## Open your existing project

In the sidebar, upload your hosted-app `stack.json`, then click **Load uploaded stack**. Its layer order, thicknesses, embedded n/k data, coherence, source settings and optional emission spectrum are retained. A `dipole_results.json` that contains a `config` object can also restore that captured configuration. A numerical result JSON without `config` cannot restore the stack.

Two examples are in `examples/`: illustrative defaults and a literature-proxy stack with the converted optical data embedded. Neither should be mistaken for your actual exported browser configuration. Read `examples/README.md` for data assumptions.

## Interface

- **Stack editor:** editable layer table, live cross-section, selected-layer roles/colors, add/remove/reorder, coherent/incoherent flags and CSV inputs. Press Enter or leave the edited cell to commit a change. Coherence `c` means coherent; `i` means incoherent. Role is assigned in the selected-layer inspector.
- **Optical constants:** three columns `wavelength_nm,n,k`; optional header, UTF-8/BOM, comma/semicolon/tab/whitespace delimiters. Each layer may have its own wavelength grid. Linear interpolation, no extrapolation. CSV values override displayed constant n/k for that layer.
- **Placement comparison:** use the dedicated move-2D control to relocate a film relative to the QDs while preserving all material data. The Load preset button replaces the entire stack and its material data after confirmation.
- **Passive optics:** wavelength range/step, angle, polarization and outside-medium indices; R/T/A plot, table and CSV/JSON exports. A 100 nm Al film gives negligible full-stack transmission.
- **Dipole emission:** orientation fraction, source plane/depth distribution, interface inset and reference wavelength. Optional two-column intrinsic emission-spectrum CSV; at most 201 points. Normalized weights account for unequal wavelength spacing. Outputs: air/glass power fractions, total electromagnetic power factor, channel bars and angular plot; JSON and CSV exports.
- **Calculations:** isolated subprocess, nonblocking status polling, cancel button, and a 10-minute per-run limit. Results carry their captured configuration. Changing inputs collapses the old results and marks them outdated; exports from that panel still belong to its captured inputs.
- **Persistence:** session-only until you export JSON. Save before refreshing, closing the tab or redeploying. Local configurations may be stored anywhere on your own computer; on Community Cloud, use download/upload rather than relying on server disk persistence.

Recommended initial source settings: reference wavelength 640 nm, horizontal fraction 2/3, source position 0.5, single source plane. Uniform source results can depend strongly on the interface inset; do not assume the default 1 nm is experimentally established.

## Deploy from GitHub to Streamlit Community Cloud

1. Create your own GitHub repository and upload this folder's **contents**. Keep `app.py`, `project.py`, `run_job.py`, `engine.py`, `dipole.py`, `MODEL.md`, and `requirements.txt` together at repository root. Also include `.streamlit/config.toml`; examples and tests are optional.
2. Open `https://share.streamlit.io/`, connect your GitHub account and choose **Create app**.
3. Select the repository and branch. Set the main file path to **`app.py`**. Select Python **3.12** in deployment settings.
4. Deploy. Dependencies install from `requirements.txt`. No secrets or API keys are needed.

This package is ready for that workflow but has not been deployed to your GitHub/Streamlit account. You choose the app's audience. On Cloud, uploaded optical data are processed on the hosting server. Do not commit personal stack data to a public repository unless you intend to publish them; users can upload them in the interface instead.

Official deployment guidance: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## CLI use without the interface

```bash
python engine.py examples/illustrative_stack.json
python dipole.py examples/illustrative_stack.json
```

These write `passive_spectrum.csv` and `dipole_results.json` in the current working directory. CLI `dipole_results.json` does not include a captured config; the interface's JSON export does. Use your own exported `stack.json` instead of the example to reproduce a specific stack. Existing output files are overwritten.

## Model scope

The supplied `engine.py` and `dipole.py` preserve the hosted application's calculation logic; they have been reformatted for reading. Passive optics use `tmm==0.2.0`. The dipole solver uses independent recursive multilayer amplitudes and Green-function/angular-spectrum integration with NumPy. The same approximations and limitations therefore remain:

- Flat, laterally infinite, isotropic films; incoherent weakly absorbing glass.
- QD source layer k is set to zero only for the dipole model. Other films keep their loss.
- No emitter self-absorption/recycling, finite electrode edges, roughness/scattering, chirality discrimination, intrinsic nonradiative recombination or electrical injection physics.
- Guided and film-loss channels are grouped; no layer-resolved dipole absorption.
- Numerical grid agreement does not prove that arbitrarily narrow lossless guided-mode poles are resolved.
- Outcoupling is not EQE. Read `MODEL.md` for equations, normalization and references.

## Verification

Tested with Python 3.12, Streamlit 1.66.1, NumPy 2.3.5, pandas 2.2.3, Plotly 6.9.0, tmm 0.2.0 (pinned in requirements).

```bash
python tests/test_callbacks.py
python tests/test_project.py
python tests/test_physics.py
python tests/test_ui.py
```

The tests cover CSV/config handling, source data preservation, homogeneous dipole limits, Fresnel agreement with tmm, near-perfect-mirror orientation limits, depth/spectral averaging, glass attenuation, UI state transitions, real worker calculations, error reporting and cancellation. UI verification uses Streamlit's AppTest; deployment on your Community Cloud account is a separate step.

## Interface fix: widget callback state

The updated `app.py` rotates editor keys without deleting live widget state during callbacks. Role/color callbacks target a captured layer identity, and retired widget events are ignored safely. Only `app.py` needs replacing in an existing installation; no solver or dependency changes are needed. Tests include queued/missing state and role changes followed by layer actions.

## Rerender fix: layer actions

Layer movement, addition/removal, imports, presets and CSV application now execute as pre-render button callbacks. They no longer interrupt a partially rendered editor with `st.rerun()`. Automatic polling is mounted only while a calculation is running. Role/color callbacks ignore unchanged values. Only `app.py` needs replacing; restart Streamlit and fully reload the browser to discard the old interface session. Optical calculations are unchanged.

Layer-derived dropdowns also rotate keys with imported/reordered configurations, preventing stale layer IDs from the previous stack. Regression coverage includes repeated up/down movement after importing embedded literature data.
