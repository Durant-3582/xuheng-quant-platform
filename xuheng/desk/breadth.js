import {api,box,date,empty,esc,fmt,metric,note,table,title} from "./lab.js";
import {rangeControl,bindRange} from "./ranges.js";
import {loadPlotly} from "./news-charts.js";

const range={days:252};
let latest;
const share=r=>r[2]?fmt(100*r[1]/r[2])+"%":"—";
export function breadthLink(row){
  return (row?note(date(row[0])+" · 有效样本中 "+share(row)+" 的股票站上 200 日均线。"):"")+
    '<a class="link-btn" href="#overview/breadth">查看 200 日均线宽度 →</a>';
}
export async function breadthPage(env){
  const head=title("200 日均线市场宽度","观察指数走势背后，有多少只股票站上了各自的长期均线。")+
    '<a class="link-btn" href="#overview">← 市场总览</a>';
  const {panel}=env;
  panel.innerHTML=head+empty("正在读取历史市场宽度…");
  try{
    if(latest?.day!==env.day){
      const data=await api("/api/studies",60000,{body:JSON.stringify({action:"breadth",asOf:env.day})});
      if(!env.current())return;
      latest={...data,day:env.day};
    }
    const rows=latest.rows,last=rows.at(-1);
    panel.innerHTML=head+'<div class="metrics">'+metric("站上均线占比",share(last),date(last[0]))+
      metric("站上均线",fmt(last[1],0),"只股票")+metric("有效样本",fmt(last[2],0),"已有 200 个有效收盘")+
      metric("当日报价但历史不足",fmt(last[3]-last[2],0),"只股票")+'</div>'+
      box("宽度与沪深 300",'<div class="controls">'+rangeControl("breadth-range","观察区间",[[60,"近 60 日"],[252,"近 1 年"],[756,"近 3 年"],[0,"全部历史"]],range)+'</div><div id="breadth-plot"></div><div id="breadth-recent"></div>')+
      note("每日以当时上市且有有效成交报价的沪、深、北 A 股为股票池。每只股票用收盘价与除权参考前收盘之比串联价格，取含当日在内最近 200 个有效收盘的算术均值。严格高于均线计入分子，历史不足及当日无有效报价的股票不进分母。北交所自 2021-11-15 起纳入。沪深 300 从正式发布日起显示点位。");
    const node=panel.querySelector("#breadth-plot"),plotly=await loadPlotly();
    if(!env.current()||!node.isConnected)return;
    async function draw(){
      const slice=range.days?rows.slice(-range.days):rows;
      const x=slice.map(r=>date(r[0]));
      const axis={type:"date",anchor:"y2",range:[x[0],x.at(-1)],gridcolor:"#e3e9e4"};
      if(x.length===1)delete axis.range;
      await plotly.react(node,[
        {type:"scatter",mode:slice.length===1?"markers":"lines",name:"均线宽度",x,y:slice.map(r=>r[2]?100*r[1]/r[2]:null),
          customdata:slice.map(r=>r.slice(1,4)),line:{color:"#176552"},hovertemplate:"%{y:.2f}% · %{customdata[0]} / %{customdata[1]} 只<extra>宽度</extra>"},
        {type:"scatter",mode:slice.length===1?"markers":"lines",name:"沪深 300",x,y:slice.map(r=>r[4]),yaxis:"y2",line:{color:"#997538"},hovertemplate:"%{y:,.2f} 点<extra>沪深 300</extra>"}
      ],{height:385,autosize:true,showlegend:false,hovermode:"x unified",margin:{l:74,r:16,t:16,b:38},xaxis:axis,
        yaxis:{domain:[0.56,1],range:[0,100],ticksuffix:"%",title:{text:"均线宽度"},gridcolor:"#e3e9e4"},
        yaxis2:{domain:[0,0.43],title:{text:"沪深 300（点）"},gridcolor:"#e3e9e4"}},
        {responsive:true,displayModeBar:false});
      panel.querySelector("#breadth-recent").innerHTML='<details><summary>查看区间末的逐日统计</summary>'+
        table(["交易日","站上均线","有效样本","当日报价","占比","沪深 300（点）"],slice.slice(-20).reverse().map(r=>[date(r[0]),fmt(r[1],0),fmt(r[2],0),fmt(r[3],0),share(r),fmt(r[4])]))+'</details>';
    }
    bindRange("breadth-range",range,draw);await draw();
  }catch(e){
    if(env.current()){
      panel.innerHTML=head+'<p class="error">'+esc(e.message||"图表暂时无法显示。")+'</p><button type="button" class="quiet">重新读取</button>';
      panel.querySelector("button").onclick=()=>breadthPage(env);
    }
  }
}
