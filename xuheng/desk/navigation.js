// Use one browser-history entry per navigation, even when Community Cloud nests
// the workbench in two frames. Links also work when copied or opened separately.
const allowed=/^(overview|indices|stocks|news|factors|backtest|portfolio)(?:\/[a-zA-Z0-9_.-]{1,40})?$/;
let addressWindow;
try {
  if (top !== window && top.location.origin === location.origin) addressWindow=top;
} catch { /* A third-party embedding page owns its own history. */ }
export const ownsAddress=Boolean(addressWindow);

function fromAddress(url) {
  let page=url.searchParams.get("page") || "overview";
  if(page==="strategies")page="backtest";
  const detail=url.searchParams.get("tab") || (
    ["stocks","indices"].includes(page)?url.searchParams.get("symbol"):null);
  const route=detail?page+"/"+detail:page;
  return allowed.test(route)?route:"overview";
}

function publicURL(route) {
  let url;
  if(addressWindow) url=new URL(addressWindow.location.href);
  else {
    url=new URL(location.href);
    url.pathname=url.hostname.endsWith(".streamlit.app")?"/":url.pathname.split("/component/")[0]+"/";
    url.search="";url.hash="";
  }
  const [page,detail]=route.split("/");
  for(const k of ["page","tab","symbol"])url.searchParams.delete(k);
  if(page!=="overview" || detail)url.searchParams.set("page",page==="backtest"?"strategies":page);
  if(detail)url.searchParams.set(["stocks","indices"].includes(page)&&detail!=="screen"?"symbol":"tab",detail);
  return url;
}

function setLocal(route, notify) {
  if(route===(location.hash.slice(1)||"overview") && location.hash)return;
  const oldURL=location.href;
  history.replaceState(history.state,"",location.pathname+location.search+"#"+route);
  if(notify)dispatchEvent(new HashChangeEvent("hashchange",{oldURL,newURL:location.href}));
}

export function navigate(route, replace=false, notify=true) {
  if(!allowed.test(route))return;
  if(addressWindow){
    const next=publicURL(route);
    if(next.href!==addressWindow.location.href){
      addressWindow.history[replace?"replaceState":"pushState"](addressWindow.history.state,"",next);
    }
  }
  setLocal(route,notify);
}

function link(anchor) {
  const route=anchor.getAttribute("href")?.slice(1);
  if(!route || !allowed.test(route))return;
  anchor.dataset.deskRoute=route;
  anchor.href=publicURL(route).href;
}

export function startNavigation(initial) {
  const first=addressWindow?fromAddress(new URL(addressWindow.location.href)):initial;
  setLocal(first||"overview",false);
  document.querySelectorAll('a[href^="#"]').forEach(link);
  new MutationObserver(records=>{
    for(const record of records)for(const el of record.addedNodes){
      if(el.nodeType!==1)continue;
      if(el.matches('a[href^="#"]'))link(el);
      el.querySelectorAll('a[href^="#"]').forEach(link);
    }
  }).observe(document.body,{subtree:true,childList:true});
  document.addEventListener("click",e=>{
    const a=e.target.closest('a[data-desk-route]');
    if(!a || e.defaultPrevented || e.button!==0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)return;
    e.preventDefault();navigate(a.dataset.deskRoute);
  });
  if(addressWindow){
    const restore=()=>setLocal(fromAddress(new URL(addressWindow.location.href)),true);
    addressWindow.addEventListener("popstate",restore);
    addEventListener("pagehide",()=>addressWindow.removeEventListener("popstate",restore),{once:true});
  }
}
