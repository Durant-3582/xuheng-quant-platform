import {api,date,esc,fmt,note,pct,table} from "./lab.js";

export function livePanel(parent, symbol="") {
  const details=document.createElement("details");
  details.className="box";
  const title=symbol?"查询 Tushare 最新日线":"Tushare 数据状态与更新日期";
  details.innerHTML='<summary>'+title+'</summary><div class="controls"><button class="quiet" type="button">'+
    (symbol?"查询接口最新报价":"检查 Tushare 最新交易日")+'</button></div><div role="status"></div>';
  parent.append(details);
  const button=details.querySelector("button"),out=details.querySelector('[role="status"]');
  button.onclick=async()=>{
    button.disabled=true;out.textContent="正在查询 Tushare…";
    try {
      const reply=await api("/api/live?"+new URLSearchParams({symbol}));
      if(symbol) {
        out.innerHTML=reply.rows.length?table(["交易日","开盘","最高","最低","收盘","日涨跌幅"],
          reply.rows.map(r=>[date(r.trade_date),fmt(r.open),fmt(r.high),fmt(r.low),fmt(r.close),pct(r.pct_chg)])):note("近 35 个自然日没有有效收盘报价。");
      } else {
        out.innerHTML=note(reply.latest?"个股与指数样本最近共同报价日 "+date(reply.latest)+"，回测库截至 "+date(reply.day)+"。":"两个样本最近没有共同的报价日。");
      }
      out.insertAdjacentHTML("beforeend",note("接口查询时间 "+reply.checked+"（北京时间）。"));
    } catch(error) {out.innerHTML=note(error.message);}
    finally {button.disabled=false;}
  };
}
