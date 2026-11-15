import {api,date,empty,esc,fmt,note,pager,select,table} from "./lab.js";

const labels={equal:"同批股票等权",tb:"同批股票 TB 配权",manual:"手动配权"};
const percentage=v=>Number.isFinite(v)?fmt(v)+"%":"—";

export function bindRisk(details,snapshot,initial,name){
  const output=details.querySelector("[data-risk-output]");
  let data,loading=false,chosen=initial,page=0;
  function draw(){
    const book=data.books[chosen];
    const summary=table(["配权方式","现金权重","年化波动率"],Object.entries(data.books).map(([k,b])=>
      [esc(labels[k]),percentage(b.cash),percentage(b.vol)]));
    const state={cash:"该组合期末全部为现金，估计波动率为零，风险贡献比例无定义。",short:"共同有效收益不足 60 日，无法可靠估计该持仓的波动率和风险贡献。",constant:"组合收益在估计窗口内几乎没有波动，风险贡献比例无定义。"};
    let body=state[book.state]?empty(state[book.state]):"";
    if(book.state==="ok"){
      const rows=book.rows.slice(page*20,(page+1)*20).map(([c,w,s,points])=>[
        esc(name(c))+" <small>"+esc(c)+"</small>",percentage(w),percentage(s),fmt(points)+" 个百分点"]);
      body=table(["期末持仓","实际权重","占组合风险","年化波动贡献"],rows)+pager("risk",page,book.rows.length,20)+
        '<details><summary>持仓收益相关性</summary>'+note("按实际权重展示前 "+book.codes.length+" 只。所有系数使用下方标明的同一批交易日；收益恒定时显示缺失。")+
        table(["股票",...book.codes.map(name)],book.matrix.map((row,i)=>[esc(name(book.codes[i]))+" <small>"+esc(book.codes[i])+"</small>",...row.map(v=>fmt(v,2))]))+'</details>';
    }
    output.innerHTML=note("按 "+date(data.end)+" 收盘实际持仓估计。两种配权逐期使用同一批候选股，开盘成交限制和费用均已计入。")+summary+
      '<div class="controls">'+select(details.id+"-style","查看组合",Object.keys(data.books).map(k=>[k,labels[k]]),chosen)+'</div>'+body+
      note("估计窗口 "+date(data.start)+" 至 "+date(data.end)+"，共 "+data.sessions+" 个市场交易日，所有参与比较的股票均有有效收益的交易日为 "+data.common+" 个。")+
      note("取各股收盘价与当日参考前收盘计算日收益，现金收益取零。风险占比为持仓权重乘以该股与组合收益的协方差，再除以组合收益方差。负贡献表示该持仓在此窗口有分散风险的作用。波动率按 252 个交易日年化。");
    output.querySelector("select").onchange=e=>{chosen=e.target.value;page=0;draw();};
    output.querySelectorAll("[data-pager]").forEach(b=>b.onclick=()=>{page+=Number(b.dataset.delta);draw();});
  }
  async function load(){
    if(!details.open||data||loading)return;
    loading=true;output.innerHTML=empty("正在读取期末前 120 个交易日的持仓收益…");
    try{
      data=await api("/api/portfolio-risk",120000,{body:JSON.stringify(snapshot)});
      if(details.isConnected)draw();
    }catch(e){
      if(details.isConnected){
        output.innerHTML=note(e.message)+'<button type="button" class="quiet">重新计算</button>';
        output.querySelector("button").onclick=load;
      }
    }finally{loading=false;}
  }
  details.addEventListener("toggle",load);
}
