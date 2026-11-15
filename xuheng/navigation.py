"""Keep the selected security, the sidebar and the shareable URL in sync."""
import streamlit as st

from .ui_common import NAV

DETAIL_PAGES = {"stocks": "stock", "indices": "index"}


def navigate(page, symbol=None):
    state = st.session_state
    state["cfg_nav"] = page
    state.pop("_show_data_details", None)
    state.pop("_unknown_symbol", None)
    kind = DETAIL_PAGES.get(page)
    if kind and symbol:
        state[f"cfg_{kind}_code"] = symbol
    values = {k: st.query_params.get_all(k) for k in st.query_params if k not in ("page", "symbol")}
    values["page"] = page
    if kind and symbol:
        values["symbol"] = symbol
    st.query_params.from_dict(values)
    state["_url_route"] = (page, symbol or "")


def sidebar_changed():
    page = st.session_state["cfg_nav"]
    kind = DETAIL_PAGES.get(page)
    navigate(page, st.session_state.get(f"cfg_{kind}_code") if kind else None)


def restore_route(store):
    state = st.session_state
    page = st.query_params.get("page", "overview")
    if page == "backtest":
        page = "strategies"
    if page not in NAV:
        page = "overview"
    symbol = st.query_params.get("symbol", "").strip().upper()
    route = (page, symbol)
    if state.get("_url_route") == route:
        return
    state["_url_route"] = route
    state["cfg_nav"] = page
    state.pop("_show_data_details", None)
    state.pop("_unknown_symbol", None)
    if symbol and page in DETAIL_PAGES:
        canonical = store.snapshot.get("aliases", {}).get(symbol, symbol)
        row = store.catalog.get(canonical)
        if row and row[2] == DETAIL_PAGES[page]:
            state[f"cfg_{row[2]}_code"] = canonical
        else:
            state["_unknown_symbol"] = symbol


def select_security(page, key):
    navigate(page, st.session_state[key])


def security_table(store, records, symbols, key):
    if not records:
        st.caption("没有符合条件的记录。")
        return

    def open_row():
        selection = st.session_state[key]["selection"]["rows"]
        if selection and 0 <= selection[0] < len(symbols):
            symbol = symbols[selection[0]]
            row = store.catalog.get(symbol)
            if row:
                navigate("indices" if row[2] == "index" else "stocks", symbol)

    st.caption("点选行首可查看证券详情。")
    st.dataframe(records, use_container_width=True, hide_index=True, key=key,
                 selection_mode="single-row", on_select=open_row)
