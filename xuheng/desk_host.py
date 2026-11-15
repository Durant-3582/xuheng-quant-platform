"""Host the research desk in Streamlit and keep data and credentials server-side."""
import base64
import gzip
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import secrets

import plotly
import streamlit as st
from streamlit.components.v1 import declare_component

from .desk_api import dispatch, release, SnapshotChanged
from .ui_common import provider_token

# Streamlit allows browsers to cache component scripts. A new asset directory
# URL lets existing visitors receive HTML, CSS and all modules as one revision.
desk_dir = Path(__file__).with_name("desk")
assets = hashlib.sha256()
for asset in sorted(desk_dir.iterdir()):
    if asset.suffix in (".html",".css",".js"):
        assets.update(asset.name.encode())
        assets.update(asset.read_bytes())
component = declare_component("v"+assets.hexdigest()[:16]+"_market_desk", path=str(desk_dir))
news_plots = declare_component("news_plotly_"+plotly.__version__.replace(".", "_"),
                               path=str(Path(plotly.__file__).parent / "package_data"))
ROUTES = {"overview", "indices", "stocks", "news", "factors", "backtest", "portfolio"}
SUBPAGES = {"overview":{"rotation","breadth"}, "factors":{"multi","test"}, "stocks":{"screen"}, "portfolio":{"research","manual"}}
HOST_STYLE = """<style>
[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],
[data-testid="stSidebar"],[data-testid="stBottom"],footer,#MainMenu {display:none!important}
[data-testid="stAppViewContainer"],[data-testid="stMain"],.main {overflow:hidden!important}
.block-container,[data-testid="stMainBlockContainer"] {max-width:none!important;margin:0!important;padding:0!important}
[data-testid="stVerticalBlock"] {gap:0!important}
.element-container:has(.stMarkdown:has(style)),[data-testid="stElementContainer"]:has(.stMarkdown:has(style)){display:none}
iframe[title$="market_desk"] {display:block!important;width:100%!important;height:100vh!important;height:100dvh!important;border:0!important}
.element-container:has(iframe[title$="market_desk"]),[data-testid="stElementContainer"]:has(iframe[title$="market_desk"]){opacity:1!important;transition:none!important}
</style>"""


@st.cache_resource(show_spinner=False)
def signing_key(provider):
    return hmac.digest(provider.encode(),"xuheng/portfolio-selection/v1".encode(),"sha256") if provider else secrets.token_bytes(32)


def clean_route(page, detail=""):
    if page=="strategies":
        page="backtest"
    if page not in ROUTES:
        return "overview"
    if detail in SUBPAGES.get(page, ()):
        return page+"/"+detail
    if page in ("indices","stocks") and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}",detail):
        return page+"/"+detail.upper()
    return page


def url_route():
    page=st.query_params.get("page","overview")
    detail=st.query_params.get("tab","") or st.query_params.get("symbol","")
    return clean_route(page,detail)


def sync_url(value):
    if not isinstance(value,str):
        return
    page,_,detail=value.partition("/")
    route=clean_route(page,detail)
    if route==url_route():
        return
    page,_,detail=route.partition("/")
    params={k:st.query_params.get_all(k) for k in st.query_params if k not in ("page","symbol","tab")}
    if page!="overview" or detail:
        params["page"]="strategies" if page=="backtest" else page
    if detail:
        params["tab" if detail in SUBPAGES.get(page, ()) else "symbol"]=detail
    st.query_params.from_dict(params)


def response(store, req, token):
    identifier=req["id"]
    path=req.get("path","")
    body=req.get("body")
    if (not isinstance(path,str) or len(path)>8000 or body is not None and not isinstance(body,dict)
            or body is not None and len(json.dumps(body,ensure_ascii=True))>65536):
        return {"id":identifier,"error":"研究查询格式无效。"}
    try:
        data=dispatch(store,path,body,signing_key(token),token)
        if req.get("gzip") is True:
            raw=json.dumps(data,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
            if len(raw)>40000:
                return {"id":identifier,"gz":base64.b64encode(gzip.compress(raw,compresslevel=2)).decode()}
        return {"id":identifier,"data":data}
    except SnapshotChanged as exc:
        return {"id":identifier,"error":str(exc),"code":"snapshot_changed"}
    except ValueError as exc:
        msg=str(exc)
        return {"id":identifier,"error":msg if re.search(r"[\u3400-\u9fff]",msg) else "参数无效，请检查输入后重试。"}
    except (TypeError,KeyError,IndexError):
        return {"id":identifier,"error":"请检查证券、参数和日期。"}
    except Exception:
        logging.getLogger(__name__).exception("Research desk request failed for %s",path.split("?")[0])
        return {"id":identifier,"error":"暂时无法读取研究数据，请重试。"}


def render(store):
    st.markdown(HOST_STYLE,unsafe_allow_html=True)
    version={"id":release(store),"catalog":store.manifest["files"]["catalog"]["sha256"],
             "day":store.day,"sample":bool(store.manifest.get("sample"))}
    req=st.session_state.get("desk_request")
    reply=st.session_state.get("_desk_reply")
    if (isinstance(req,dict) and isinstance(req.get("id"),str) and len(req["id"])<=96
            and (not reply or req["id"]!=reply["id"])):
        if req.get("clientRouting") is not True:
            sync_url(req.get("route"))
        reply=response(store,req,provider_token())
        st.session_state["_desk_reply"]=reply
    component(key="desk_request",default=None,reply=reply,initialRoute=url_route(),version=version,
              newsPlots=news_plots.name)
