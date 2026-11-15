import {api,requireDay,DataDateError,offerRefresh, box, date, fmt, focusTable, line, metric, note, pct, select, signed, pager, table, title, valuationNote,executionNote} from "./lab.js";

const rules = [["mom", "60 日动量"], ["vol", "20 日低波动"]];
const markets = [["", "全 A 股"], ["SH", "沪市"], ["SZ", "深市"], ["BJ", "北交所"]];
const samples = new Map();

async function readResult(day,options){
  const {factor,exchange,count,fee,from,to}=options;
  const params=new URLSearchParams({factor,exchange,count,fee,from,to,asOf:day});
  const key=day+"|"+params;if(samples.has(key))return samples.get(key);
  const data=await api("/api/strategy?"+params,90000);
  requireDay(data.day,day);
  if(samples.size>=8)samples.delete(samples.keys().next().value);samples.set(key,data);return data;
}
function results(sim) {
  const metrics = metric("策略累计收益", pct(sim.total), "已计交易成本")
    + metric("最大回撤", pct(sim.dd), "按月末及末期净值")
    + metric("平均双边换手", fmt(sim.turn)+"%", "实际买卖金额之和 ÷ 调仓前资产")
    + metric("调仓期数", String(sim.logs.length));
  return '<div class="metrics">' + metrics + '</div>'+executionNote(sim.execution,"策略",sim.limitCoverage)+valuationNote(sim.valuation,"策略",sim.total)
    + box("策略与基准净值", line("bt-chart") + '<div id="bt-legend"></div><p id="bt-comparison" class="note" role="status"></p>')
    + box("调仓记录",'<div id="bt-log"></div>'+note("月末收盘选股，下一个交易日开盘建仓。最大回撤只看月末（或本期最后收盘），不包含月内的下跌。缺有效开盘报价不成交；开盘触及涨停不买、跌停不卖。优先使用 Tushare 逐股限价，2007 年前或缺限价时按常见幅度保守估算；卖不出的旧仓保留。按实际买入与卖出金额分别扣费。期末没有报价的旧仓沿用末次价格，未模拟最终退市清偿。"));
}
function ledger(area,logs){
  let page=0;const all=[...logs].reverse();
  function fill(){
    const rows=all.slice(page*24,page*24+24).map(l=>[date(l.signal),date(l.entry),date(l.end),l.n+" / "+l.filled,String(l.held),String(l.stale),pct(l.turn),signed(l.ret)]);
    area.innerHTML=table(["信号日","开盘调仓日","期末","候选 / 实际持有候选","实际持仓","期末缺报价","双边换手","净收益"],rows)+pager("strategy",page,all.length,24);
    area.querySelectorAll("button").forEach(b=>b.onclick=()=>{page+=Number(b.dataset.delta);fill();focusTable(area);});
  }
  fill();
}

export function backtest({panel, day, remember, settings, benchmarks, refresh, isCurrent, chart, legend}) {
  const controls = select("bf", "选股规则", rules, settings.factor)
    + select("bx", "范围", markets, settings.exchange)
    + '<label>持股数 <input id="bn" type="number" min="1" max="200" required value="' + settings.count + '"></label>'
    + '<label>单边成本（基点） <input id="bc" type="number" min="0" max="100" step="0.1" required value="' + settings.fee + '"></label>'
    + select("bb", "比较基准", benchmarks, settings.benchmark)
    + '<label>信号起日 <input id="bfro" type="date" min="2000-01-01" max="' + date(day) + '" value="' + (settings.from ? date(settings.from) : "") + '"></label>'
    + '<label>截止日 <input id="bto" type="date" min="2000-01-01" max="' + date(day) + '" value="' + (settings.to ? date(settings.to) : "") + '"></label>';
  panel.innerHTML = title("策略回测", "用过去每个月末已经公布的行情选股，模拟下一交易日买入，查看扣费后的历史收益，并与指数比较。")
    + box("策略参数", '<form id="bt-form" novalidate><div class="controls">' + controls + '</div>'
      + '<div class="actions"><button class="act" id="bt-run" type="submit">运行回测</button>'
      + '<span id="bt-status" role="status" aria-live="polite"></span></div></form>'
      + '<p id="bt-range" class="note">日期留空时使用完整调仓样本。月末收盘形成信号，下一交易日开盘等权建仓。</p>')
    + '<div id="bt-output"></div>';

  const field = id => panel.querySelector("#" + id);
  const form = field("bt-form"), button = field("bt-run"), status = field("bt-status"), out = field("bt-output");
  let revision = 0, completedRuns = 0, first = "", last = "";
  let autoStart = settings.autoStart !== false, autoEnd = settings.autoEnd !== false;
  function feedback(message, state) {
    status.dataset.state = state;
    status.textContent = message;
    button.disabled = state === "running";
    button.textContent = button.disabled ? "正在运行…" : "运行回测";
    out.setAttribute("aria-busy", String(button.disabled));
  }
  function resetRange() {
    autoStart = autoEnd = true;
    field("bfro").value = "";
    field("bto").value = "";
    run(true);
  }
  form.addEventListener("input", event => {
    if (event.target.id === "bfro") autoStart = !event.target.value;
    if (event.target.id === "bto") autoEnd = !event.target.value;
    if (autoStart && (event.target.id === "bf" || event.target.id === "bx")) field("bfro").value = "";
    ++revision;
    out.replaceChildren();
    feedback("参数已修改，点击「运行回测」查看新结果。", "edited");
  });
  function readInputs() {
    const count = field("bn"), fee = field("bc"), start = field("bfro"), end = field("bto");
    const invalid = [
      [count, !count.validity.valid, "持股数须为 1 至 200 的整数。"],
      [fee, !fee.validity.valid, "单边成本须为 0 至 100 个基点，最多一位小数。"],
      [start, !start.validity.valid, "请输入有效的信号起日，或清空以使用样本起点。"],
      [end, !end.validity.valid, "请输入有效的截止日，或清空以使用样本终点。"],
      [end, start.value && end.value && start.value > end.value, "截止日早于信号起日，请调整日期。"]
    ].find(([, failed]) => failed);
    if (invalid) {
      feedback(invalid[2], "error");
      invalid[0].focus();
      return null;
    }
    return {factor: field("bf").value, exchange: field("bx").value, count: count.valueAsNumber,
      fee: fee.valueAsNumber, benchmark: field("bb").value,
      from: start.value.replaceAll("-", ""), to: end.value.replaceAll("-", "")};
  }

  async function compareBenchmark(curve, code, current) {
    const strategy = {name: "策略", data: curve};
    const name = benchmarks.find(([value]) => value === code)?.[1] || code;
    const message = field("bt-comparison");
    chart("bt-chart", [strategy]);
    field("bt-legend").innerHTML = legend(["策略"]);
    message.textContent = "正在读取" + name + "的比较净值…";
    try {
      const params = new URLSearchParams({symbol: code, asOf:day, quoteStart:curve[0][0], days: curve.map(([day]) => day).join(",")});
      const {closes,listed,until} = await api("/api/series?" + params, 12000);
      if (!current()) return;
      requireDay(until,day);
      const values = new Map(closes);
      const common = curve.filter(([day]) => (!listed || day>=listed) && values.get(day)>0);
      if (common.length < 2) {
        message.textContent = name + "在所选区间缺少可比报价，可以更换比较基准。";
        return;
      }
      const [firstDay, firstLevel] = common[0], base = values.get(firstDay);
      const data = common.map(([day]) => [day, firstLevel * values.get(day) / base]);
      chart("bt-chart", [strategy, {name, data}]);
      field("bt-legend").innerHTML = legend(["策略", name]);
      message.textContent = firstDay !== curve[0][0]
        ? name + "从发布后首个可比时点 " + date(firstDay) + " 接入，当天以策略净值为起点。更早的日期仅显示策略曲线。"
        : common.length < curve.length ? "部分日期缺少基准报价，仅显示有报价的基准点。" : "策略与指数从同日开盘的 100 起算。";
    } catch (error) {
      if (!current()) return;
      message.textContent = name + "比较线未载入。" + error.message + " ";
      if(offerRefresh(message,error,refresh))return;
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "quiet";
      retry.textContent = "重试比较基准";
      retry.onclick = () => { if (current()) compareBenchmark(curve, code, current); };
      message.append(retry);
    }
  }

  async function run(manual) {
    const request = ++revision;
    const current = () => isCurrent() && request === revision;
    const options = readInputs();
    out.replaceChildren();
    if (!options) return;
    feedback("正在读取调仓样本并计算收益…", "running");
    try {
      // Yield for a paint even when the requested sample is already in memory.
      await new Promise(resolve => setTimeout(resolve, 24));
      if (!current()) return;
      if(autoStart)options.from="";if(autoEnd)options.to="";
      const sample=await readResult(day,options);
      if (!current()) return;
      first = sample.first;
      last = sample.last;
      field("bt-range").textContent = "可回测样本 " + date(first) + " 至 " + date(last)
        + "。从信号起日之后（含当日）的首个月末选股，下一交易日开盘建仓。截止日只计入已经结束的持有期。";
      if (autoStart || !options.from) { options.from = first; field("bfro").value = date(first); }
      if (autoEnd || !options.to) { options.to = last; field("bto").value = date(last); }
      Object.assign(settings, options, {autoStart, autoEnd});
      const sim=sample.sim;
      if (!sim?.logs.length) {
        feedback("所选范围和日期没有完整调仓期。", "error");
        out.innerHTML = '<button class="quiet" type="button" id="bt-reset">使用完整样本区间</button>';
        field("bt-reset").onclick = resetRange;
        return;
      }
      remember(sim.logs[0].entry, sim.logs.at(-1).end);
      out.innerHTML=results(sim);ledger(field("bt-log"),sim.logs);
      const rule = rules.find(([id]) => id === options.factor)[1];
      const market = markets.find(([id]) => id === options.exchange)[1];
      const completion = manual ? "第 " + (++completedRuns) + " 次回测完成" : "已按当前参数自动回测";
      feedback(completion + " · " + rule + " · " + market + " · 目标 " + options.count + " 只 · "
        + sim.logs.length + " 期 · 累计收益 " + pct(sim.total), "done");
      if (manual && out.getBoundingClientRect().top >= window.innerHeight) out.scrollIntoView({block: "start"});
      compareBenchmark(sim.curve, options.benchmark, current);
    } catch (error) {
      if (current()){feedback(error.message+(error instanceof DataDateError?"":" 可以再次点击「运行回测」。"),"error");offerRefresh(status,error,refresh);}
    }
  }
  form.onsubmit = event => { event.preventDefault(); run(true); };
  run(false);
}
