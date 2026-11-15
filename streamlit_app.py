import streamlit as st

from xuheng.archive import ArchiveError
from xuheng.desk_host import render
from xuheng.ui_common import access, connection

st.set_page_config(page_title="序衡 · A 股量化研究", page_icon="📈", layout="wide", initial_sidebar_state="collapsed",
                   menu_items={"Get Help":None, "Report a Bug":None, "About":"序衡 · 金融工程课程研究工作台"})
access()
try:
    render(connection())
except ArchiveError as exc:
    st.error(str(exc))
    st.button("重新读取行情")
