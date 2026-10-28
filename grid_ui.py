"""Editable, selectable, draggable layer grid. Only scalar display data reach JS;
material spectra stay in Python and follow immutable layer IDs.
"""

from __future__ import annotations
import copy
import math
from st_aggrid import AgGrid, JsCode, DataReturnMode
import pandas as pd


def rows_for_grid(layers):
    return [
        dict(
            id=l["id"],
            name=l["name"],
            d=l["d"],
            n=l["n"],
            k=l["k"],
            coherence=l["coherence"],
            role=l["role"],
            has_csv=bool(l.get("data")),
            optical_data=(
                f"CSV · {len(l['data'])} points" if l.get("data") else "Constants"
            ),
        )
        for l in layers
    ]


def merge_grid_rows(layers, rows):
    """Validate the entire edit/reorder atomically, keeping all non-table data."""
    lookup = {l["id"]: l for l in layers}
    if not isinstance(rows, list) or len(rows) != len(layers):
        raise ValueError("Grid must return every existing layer exactly once.")
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(lookup):
        raise ValueError("Grid layer identities do not match the current stack.")
    result = []
    for row in rows:
        l = copy.deepcopy(lookup[row["id"]])
        name = row.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Each layer needs a name of 1–100 characters.")
        l["name"] = name.strip()
        for key in ("d", "n", "k"):
            value = float(row[key])
            if not math.isfinite(value) or (value < 0 if key == "k" else value <= 0):
                raise ValueError("Use positive thickness/n and nonnegative k.")
            # Uploaded optical tables override constants; do not accidentally
            # replace those fallbacks with frontend edits to disabled cells.
            if key == "d" or not l.get("data"):
                l[key] = value
        if row.get("coherence") not in ("c", "i"):
            raise ValueError("Coherence must be c or i.")
        l["coherence"] = row["coherence"]
        result.append(l)
    return result


COLLECT = JsCode("""function({streamlitRerunEventTriggerName, eventData}) {
    const api=eventData.api, rows=[];
    for(let i=0;i<api.getDisplayedRowCount();i++) {
        const node=api.getDisplayedRowAtIndex(i);
        if(node && node.data) rows.push({...node.data});
    }
    const selected=api.getSelectedRows();
    const id=eventData.node && eventData.node.data ? eventData.node.data.id
             : (selected.length ? selected[0].id : null);
    return {rows:rows,selected_id:id,event:streamlitRerunEventTriggerName,
            revision:api.getGridOption('context').revision};
}""")
RESIZE = JsCode("""function(params) {
    const w=Math.max(380, params.clientWidth-2), widths=[.36,.28,.18,.18];
    params.api.setColumnWidths(['name','d','n','k'].map((key,i)=>
        ({key:key,newWidth:Math.floor(w*widths[i])})),true);
}""")
SELECT = JsCode("""function(params) {
    const id=params.api.getGridOption('context').selectedId;
    params.api.forEachNode(node=>node.setSelected(node.data.id===id));
}""")


def layer_grid(layers, selected_id, revision, callback):
    editable_index = JsCode("function(p){return !p.data.has_csv;}")
    positive = JsCode(
        "function(p){const v=Number(p.newValue);return Number.isFinite(v)&&v>0?v:p.oldValue;}"
    )
    nonnegative = JsCode(
        "function(p){const v=Number(p.newValue);return Number.isFinite(v)&&v>=0?v:p.oldValue;}"
    )
    options = dict(
        columnDefs=[
            dict(
                field="name",
                headerName="Material",
                width=210,
                minWidth=120,
                rowDrag=True,
                pinned="left",
                cellEditor="agTextCellEditor",
                cellEditorParams=dict(maxLength=100),
            ),
            dict(
                field="d",
                headerName="Thickness · nm",
                width=150,
                minWidth=100,
                cellEditor="agNumberCellEditor",
                cellEditorParams=dict(min=0.001, precision=4),
                valueParser=positive,
            ),
            dict(
                field="n",
                headerName="n",
                width=100,
                minWidth=70,
                editable=editable_index,
                headerTooltip="Constant n; ignored when CSV data are loaded.",
                valueParser=positive,
            ),
            dict(
                field="k",
                headerName="k",
                width=100,
                minWidth=70,
                editable=editable_index,
                headerTooltip="Constant k; ignored when CSV data are loaded.",
                valueParser=nonnegative,
            ),
            dict(
                field="coherence",
                headerName="Coherence",
                width=115,
                cellEditor="agSelectCellEditor",
                cellEditorParams=dict(values=["c", "i"]),
            ),
            dict(field="role", headerName="Role", width=110, editable=False),
            dict(
                field="optical_data",
                headerName="Optical data",
                width=185,
                editable=False,
            ),
            dict(field="id", hide=True, editable=False),
            dict(field="has_csv", hide=True, editable=False),
        ],
        defaultColDef=dict(
            editable=True,
            sortable=False,
            filter=False,
            resizable=True,
            suppressMovable=True,
            suppressHeaderMenuButton=True,
        ),
        getRowId=JsCode("function(p){return p.data.id;}"),
        rowSelection=dict(
            mode="singleRow", enableClickSelection=True, checkboxes=False
        ),
        selectionColumnDef=dict(suppressHeaderMenuButton=True),
        rowDragManaged=True,
        animateRows=True,
        suppressMoveWhenRowDragging=True,
        singleClickEdit=False,
        stopEditingWhenCellsLoseFocus=True,
        rowHeight=33,
        headerHeight=36,
        context=dict(revision=revision, selectedId=selected_id),
        onGridSizeChanged=RESIZE,
        onFirstDataRendered=SELECT,
        onRowDataUpdated=SELECT,
        suppressCellFocus=False,
        alwaysShowHorizontalScroll=True,
    )
    return AgGrid(
        pd.DataFrame(rows_for_grid(layers)),
        gridOptions=options,
        height=min(465, 36 + 33 * len(layers) + 24),
        key=f"layer_grid_{revision}",
        theme="streamlit",
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        data_return_mode=DataReturnMode.CUSTOM,
        custom_jscode_for_grid_return=COLLECT,
        update_on=["rowClicked", "cellValueChanged", "rowDragEnd"],
        callback=callback,
        show_toolbar=False,
        server_sync_strategy="server_wins",
        custom_css={
            ".ag-root-wrapper": {"border-radius": "10px"},
            ".ag-header-cell-text": {"font-size": "12px"},
            ".ag-cell": {"font-size": "13px"},
            ".ag-row-selected": {"background-color": "#d5e9e3 !important"},
        },
    )
