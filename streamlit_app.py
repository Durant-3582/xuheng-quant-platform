import streamlit as st
from streamlit.components.v1 import html

from xuheng.ui_common import NAV,access,connection,iso,option
from xuheng.archive import ArchiveError
from xuheng.navigation import restore_route,sidebar_changed
from xuheng.ui_portfolio import portfolio_page
from xuheng.ui_research import data_details,factors,overview,security,strategy

st.set_page_config(page_title="序衡 · A 股投研",page_icon="📈",layout="wide",initial_sidebar_state="auto",
                   menu_items={"Get Help":None,"Report a Bug":None,"About":"序衡 · 金融工程课程研究工作台"})
# Streamlit's English shell otherwise causes browsers to translate existing Chinese labels.
# This same-origin, local component changes only the language metadata of our own page.
html("""<script>try {const d=parent.document; d.documentElement.lang='zh-CN';
d.documentElement.setAttribute('translate','no');d.documentElement.classList.add('notranslate');
if(!d.querySelector('meta[name=google][content=notranslate]')){const m=d.createElement('meta');
m.name='google';m.content='notranslate';d.head.appendChild(m);}}catch(_) {}</script>""",height=0)
st.markdown("""<style>
.block-container {max-width:82rem;padding-top:2.9rem;padding-bottom:2rem;}
h1 {letter-spacing:.015em;font-size:2.15rem!important}
h2 {font-size:1.52rem!important}
h3 {font-size:1.25rem!important}
[data-testid="stMetricValue"] {font-size:1.55rem}
[data-testid="stSidebar"] [role="radiogroup"] {gap:.35rem}
[data-testid="stSidebar"] [role="radiogroup"] label {padding:.45rem 0}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {color:#125846;font-weight:650}
[data-testid="stSidebar"] .block-container {padding-top:2.2rem}
@media (max-width:700px){.block-container{padding-top:3.3rem;padding-left:1rem;padding-right:1rem}}
</style>""",unsafe_allow_html=True)

access()
try:
    store=connection()
    release=(store.day,store.manifest['files']['catalog']['sha256'])
    if st.session_state.get('_data_release',release)!=release:
        for key in ('range_sig','range_output','strategy_sig','strategy_output','study_sig','study_train',
                    'study_review','study_test','frozen_study','study_locked_roster','study_release',
                    'restore_locked_roster','stock_last_extra','index_last_extra'):
            st.session_state.pop(key,None)
        st.info('行情库已切换。已保留研究参数，请重新运行以查看当前数据的结果。')
    st.session_state['_data_release']=release
    if store.manifest.get('sample'):
        st.info('开发验收样本 · 10 只股票、8 个指数，自 2023 年起。排名、市场统计和组合仅针对这个样本。')
    # Streamlit normally deletes unrendered widget state. Keep research inputs across views.
    for k in list(st.session_state):
        if k.startswith("cfg_"):st.session_state[k]=st.session_state[k]
    with st.sidebar:
        st.title("序衡");st.caption("A 股量化投研工作台")
        restore_route(store)
        page=st.radio("研究工作台",list(NAV),format_func=lambda k:NAV[k],key="cfg_nav",on_change=sidebar_changed)
        st.button("数据说明",key="show_data_details",on_click=st.session_state.update,args=({"_show_data_details":True},))
        st.divider();st.caption("Tushare Pro · 盘后日线");st.write("数据截至 "+iso(store.day))
    if st.session_state.get("_show_data_details"):data_details(store)
    elif page=="overview":overview(store)
    elif page=="indices":security(store,True)
    elif page=="stocks":security(store)
    elif page=="factors":factors(store)
    elif page=="strategies":strategy(store)
    elif page=="portfolio":portfolio_page(store)
except ArchiveError as exc:
    st.error(str(exc))
