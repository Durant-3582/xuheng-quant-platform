import streamlit as st

from xuheng import APP_TITLE
from xuheng.archive import ArchiveError
from xuheng.desk_host import render
from xuheng.ui_common import access, connection

st.set_page_config(page_title=APP_TITLE, page_icon="📈", layout="wide", initial_sidebar_state="collapsed",
                   menu_items={"Get Help":None, "Report a Bug":None, "About":APP_TITLE})
access()
try:
    render(connection())
except ArchiveError as exc:
    st.error(str(exc))
    st.button("重新读取行情")
