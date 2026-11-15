import {esc, fmt, note, pct, table} from "./lab.js";
import {relativeStrength} from "./diagnosis.js";

const period = (start, end) => start + " 至 " + end;
const signedPercent = r => pct(Number((r * 100).toFixed(2)));
const direction = (value, positive, negative, equal) => value > 0 ? positive : value < 0 ? negative : equal;
const rowsTable = (labels, rows) => '<div class="diagnosis-data">' + table(labels, rows) + '</div>';

function finding(key, title, conclusion, evidence) {
  return '<details data-evidence="' + key + '"><summary><span class="diagnosis-title">' + esc(title) +
    '</span><strong>' + esc(conclusion) + '</strong><span class="diagnosis-toggle">' +
    '<span>查看依据</span><span>收起依据</span></span></summary><div class="diagnosis-evidence">' +
    evidence + '</div></details>';
}

function trend(stock) {
  const {anchor, days, end, growth, invalidPrices, sessions} = stock;
  if (!anchor || growth === null) {
    const reason = !anchor ? "已取得 " + sessions.length + " 个有成交的收盘日，需要 1 个起点和随后 20 个成交日。" :
      "以下日期的成交量、收盘或参考前收盘记录不完整：" + invalidPrices.map(b=>b.day).join("、") + "。";
    return finding("trend","价格趋势","暂不能计算 20 日收益",note(reason));
  }
  const percentage = Number((growth*100).toFixed(2));
  const verdict = "近 20 个成交日" + direction(percentage,"累计上涨 ","累计下跌 ","累计涨跌约为 ") +
    fmt(Math.abs(percentage)) + "%";
  const method = "从 " + anchor.day + " 收盘起算，至 " + end.day +
    " 收盘。逐日连乘（收盘价 ÷ 当日除权参考前收盘价），再减 1。";
  return finding("trend","价格趋势",verdict,note(method) +
    rowsTable(["成交日","参考前收盘（元）","收盘（元）","当日收益"],
      days.map(b=>[esc(b.day),fmt(b.pre_close,3),fmt(b.close,3),signedPercent(b.close/b.pre_close-1)])));
}

function strength(stock, market) {
  const label = "相对强弱";
  if (market.state !== "ready") return benchmarkUnavailable("relative",label,market);
  const r = relativeStrength(stock,market);
  const reference = market.name + "（" + market.code + "）";
  if (r.reason) return finding("relative",label,"暂不能与" + market.name + "比较",
    note(reference + " · " + r.reason) + (stock.anchor ? note("个股比较区间为 " + period(stock.anchor.day,stock.end.day) + "。") :
      note("现有 " + stock.sessions.length + " 个有成交的收盘日，完整比较需要 21 个。")));
  const pp = Number((r.difference*100).toFixed(2));
  const verdict = pp === 0 ? "与" + market.name + "收益持平（至 0.01 个百分点）" :
    (pp > 0 ? "跑赢" : "落后") + market.name + " " + fmt(Math.abs(pp)) + " 个百分点";
  return finding("relative",label,verdict,note(period(r.start.day,r.end.day) + "，两端均按收盘比较。") +
    rowsTable(["比较项目","数据依据"],[
      ["个股累计收益",signedPercent(stock.growth) + "（逐日价格见「价格趋势」）"],
      [esc(reference) + " 起点 / 终点",fmt(r.start.close,4) + " / " + fmt(r.end.close,4) + " 点"],
      ["基准区间收益",signedPercent(r.growth) + "（终点 ÷ 起点 − 1）"],
      ["收益差",fmt(r.difference*100) + " 个百分点（个股收益 − 基准收益）"]
    ]));
}

function activity(stock) {
  const {days, turnover, invalidAmounts, end} = stock;
  if (!turnover || turnover.change === null) {
    const reason = days.length < 20 ? "现有 " + days.length + " 个有成交的收盘日，需要 20 个。" :
      invalidAmounts.length ? "以下日期的交易或成交额记录不完整：" + invalidAmounts.map(b=>b.day).join("、") + "。" :
      "20 日平均成交额为零，无法计算相对变化。";
    return finding("amount","成交活跃度","暂不能比较日均成交额",note(reason));
  }
  const gap = Number((turnover.change*100).toFixed(2));
  const verdict = gap === 0 ? "近 5 日与近 20 日日均成交额持平（至 0.01%）" :
    "近 5 日日均成交额比近 20 日" + (gap>0 ? "高 " : "低 ") + fmt(Math.abs(gap)) + "%";
  return finding("amount","成交活跃度",verdict,
    note("近 5 日（" + period(days.at(-5).day,end.day) + "）日均 " + fmt(turnover.five/10) +
      " 万元。近 20 日（" + period(days[0].day,end.day) + "）日均 " + fmt(turnover.twenty/10) + " 万元。") +
    note("两个窗口都截至最近成交日。变化 = 5 日均额 ÷ 20 日均额 − 1。") +
    rowsTable(["成交日","成交额（万元）","计入窗口"],days.map((b,i)=>[esc(b.day),fmt(b.amount/10,3),i>=15?"5 日及 20 日":"20 日"])));
}

function benchmarkUnavailable(key, title, market) {
  const waiting = market.state === "loading";
  return finding(key,title,waiting ? "正在读取" + market.name + "…" : "基准行情暂不可用",
    note(market.name + "（" + market.code + "）" + (waiting ? " · 正在读取日线。" : " · 可在下方的滚动 Beta 图重试。")));
}

function sensitivity(stock, market) {
  const label = "市场敏感度";
  if (market.state !== "ready") return benchmarkUnavailable("risk",label,market);
  const {latest, pairs} = market.beta;
  const reference = market.name + "（" + market.code + "）";
  if (!market.launch) return finding("risk",label,"暂不能估计 120 日 Beta",note(reference + "缺少可核对的发布日期。"));
  const selection = "只用个股与指数覆盖同一交易日的日收益。指数从发布日期起使用，停牌及跨日复牌收益跳过。";
  if (!latest) return finding("risk",label,"暂不能估计 120 日 Beta",
    note(reference + " · 共有 " + pairs + " 对有效单日收益，需要 120 对。") + note(selection) +
    (market.launch ? note("基准发布日期 " + market.launch + "。") : ""));
  const {start,end,covariance,variance,value,observations} = latest;
  let verdict = value === null ? "基准收益变动不足，无法估计 Beta" :
    "相对" + market.name + "的 120 日 Beta 为 " + fmt(Number(value.toFixed(3)),3);
  if (end !== stock.end.day) verdict += "（估计截至 " + end + "）";
  return finding("risk",label,verdict,note(reference + " · " + period(start,end) + " · " + observations.length + " 对日收益。") +
    note("Beta = 个股与基准的样本协方差 ÷ 基准的样本方差。两项分别为 " +
      fmt(covariance*10000,6) + " 和 " + fmt(variance*10000,6) + "（百分点²），衡量个股对该基准日收益的历史敏感度。") +
    note(selection) + rowsTable(["配对日","个股日收益（%）","基准日收益（%）"],
      observations.map(([x,y,d])=>[esc(d),fmt(y*100,6),fmt(x*100,6)])));
}

export function renderDiagnosis(target, info, market) {
  const stock = info.windows;
  if (!stock.end) {
    target.innerHTML = note("没有同时具备有效收盘价和成交量的日线，暂不能形成诊断。");
    return;
  }
  const open = new Set([...target.querySelectorAll("details[open]")].map(e=>e.dataset.evidence));
  const focus = document.activeElement?.closest("#stock-diagnosis details > summary")?.parentElement.dataset.evidence;
  const stale = stock.end.day !== info.release;
  const stamp = info.status === "D" ? "已退市 · 最后有效成交日 " + stock.end.day :
    stale ? "末次成交诊断 · 最后有效成交日 " + stock.end.day : "诊断截至 " + stock.end.day;
  const dates = info.status === "D" || stale ? stamp + " · 行情库截至 " + info.release : stamp;
  target.innerHTML = '<p class="diagnosis-asof">' + esc(dates) + ' · Tushare 盘后日线</p>' +
    trend(stock) + strength(stock,market) + activity(stock) + sensitivity(stock,market);
  for (const section of target.querySelectorAll("details")) {
    if (open.has(section.dataset.evidence)) section.open = true;
    if (focus === section.dataset.evidence) section.querySelector("summary").focus({preventScroll:true});
  }
}
