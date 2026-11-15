import {api, box, empty, esc, fmt, metric, note, table, title} from "./lab.js";
import {searchField} from "./search.js";
import {clearNewsCharts, renderNewsCharts} from "./news-charts.js";

function articleLink(a) {
  return '<a class="news-headline" target="_blank" rel="noopener noreferrer" href="https://finance.eastmoney.com/a/' +
    encodeURIComponent(a.id) + '.html">' + esc(a.title) + '</a>';
}

export function summarize(articles) {
  const groups = new Map();
  const lastHour = articles[0].time.slice(0,13).replace(" ","T");
  const last = Date.parse(lastHour + ":00:00Z");
  // Use Beijing wall-clock labels throughout, including in browsers in other time zones.
  const hours = Array.from({length:24}, (_,i) => ({
    key:new Date(last - (23-i)*3600000).toISOString().slice(0,13), count:0, sum:0
  }));
  const byHour = new Map(hours.map(h=>[h.key,h]));
  const positive = [], negative = [];
  let sum = 0;
  for (const a of articles) {
    sum += a.score;
    if (a.score > 52.5) positive.push(a);
    if (a.score < 47.5) negative.push(a);
    const h = byHour.get(a.time.slice(0,13).replace(" ","T"));
    if (h) { h.count++; h.sum += a.score; }
    for (const name of a.sectors) {
      const g = groups.get(name) || {name,count:0,sum:0,pos:0};
      g.count++; g.sum += a.score; if (a.score > 52.5) g.pos++;
      groups.set(name,g);
    }
  }
  positive.sort((a,b)=>b.score-a.score);
  negative.sort((a,b)=>a.score-b.score);
  const sectors = [...groups.values()].filter(g=>g.count>=2)
    .sort((a,b)=>b.count-a.count || a.name.localeCompare(b.name,"zh")).slice(0,12);
  return {mean:sum/articles.length,positive,negative,hours,sectors};
}

function headlines(items) {
  if (!items.length) return empty("本批快讯没有符合条件的标题。");
  return '<ol class="news-headlines">' + items.slice(0,6).map(a=>
    '<li>'+articleLink(a)+'<small>'+esc(a.time.slice(5,16))+' · 情绪分 '+fmt(a.score,1)+'</small></li>'
  ).join("") + '</ol>';
}

export function newsPage({panel, wireInput, name, isCurrent}) {
  const id = k=>panel.querySelector("#news-"+k);
  const syncPeriod = 5 * 60 * 1000;
  let edition, selected = "", generation = 0, nodes;
  let timer, nextSync = 0, busy = false, closed = false;
  panel.innerHTML = title("新闻情绪","观察财经快讯的措辞、行业热度，以及与具体股票有关的报道。") +
    '<details class="news-help"><summary>这页在做什么？</summary>'+
    note("先看市场和行业集中讨论什么，再用股票名称或代码核对相关报道。分数表示快讯用词的正负倾向。")+'</details>'+
    '<div class="news-controls"><button id="news-refresh" class="act" type="button">刷新新闻</button>' +
    '<span class="dim">东方财富 7×24 快讯 · 云端每半小时采集，页面每 5 分钟同步 · 北京时间</span></div>' +
    '<p id="news-status" class="news-status" role="status"></p><div id="news-summary"></div>' +
    box("个股相关新闻",searchField("news-stock","输入股票名称或代码，例如 贵州茅台 或 600519")+
      '<div id="news-stock-result" aria-live="polite"></div>') +
    '<details class="box news-method"><summary>这个指标怎么算？</summary>' +
    note("对每条快讯的标题和摘要前 300 个字符匹配正负面词，每个词计一次。情绪分 = 50 + 50 ×（正面权重 − 负面权重）÷（正面权重 + 负面权重 + 1.5）。市场情绪取本批快讯的算术平均。") +
    note("单条大于 52.5 分计作正面，小于 47.5 分计作负面，其余计作中性。行业按关键词归类，同一条可涉及多个行业。个股按行情库名称、证券代码或来源标注匹配。") +
    note("词表对否定或反讽不敏感，例如“暂无回购计划”也可能命中“回购”。点击标题可核对原文。") + '</details>';
  const status = id("status"), refresh = id("refresh"), summary = id("summary"), search = id("stock");

  function stockResult() {
    const area = id("stock-result");
    if (!selected || !edition) { area.replaceChildren(); return; }
    const hits = edition.articles.filter(a=>a.stocks.includes(selected));
    const label = name(selected)+"（"+selected+"）";
    if (!hits.length) {
      area.innerHTML = note("本批 "+edition.articles.length+" 条快讯未提及"+label+"。可查的时段见上方样本范围。");
      return;
    }
    const avg = hits.reduce((sum,a)=>sum+a.score,0)/hits.length;
    area.innerHTML = '<p class="news-selection">'+esc(label)+' · '+hits.length+' 条 · 平均情绪分 <b>'+fmt(avg,1)+'</b></p>'+
      table(["发布时间","标题","情绪分"],hits.map(a=>[esc(a.time),articleLink(a),fmt(a.score,1)]));
  }
  wireInput("news-stock","stock",code=>{
    selected = code;
    search.value = name(code)+" · "+code;
    stockResult();
  });
  search.addEventListener("input",()=>{ selected=""; stockResult(); });

  function paint() {
    const hoursOpen = summary.querySelector("details")?.open;
    clearNewsCharts(nodes);
    const list = edition.articles, stats = summarize(list), count = list.length;
    const share = n=>fmt(n/count*100,1)+"%";
    const classification = stats.mean>=55?"偏暖":stats.mean<=45?"偏冷":"中性";
    const hoursTable = table(["小时（北京时间）","条数","平均情绪分"],stats.hours.map(h=>
      [esc(h.key.replace("T"," "))+":00",String(h.count),h.count?fmt(h.sum/h.count,1):"—"]));
    const sectors = stats.sectors;
    summary.innerHTML = '<div class="metrics">'+metric("新闻情绪",fmt(stats.mean,1),classification+" · 满分 100")+
      metric("正面新闻",stats.positive.length+" 条",share(stats.positive.length))+
      metric("负面新闻",stats.negative.length+" 条",share(stats.negative.length))+
      metric("样本",count+" 条","最新 "+list[0].time.slice(5,16))+'</div>'+
      '<div class="two news-charts">'+box("市场情绪",'<div class="news-plot" id="news-gauge" role="img" aria-label="市场情绪 '+fmt(stats.mean,1)+' 分"></div>')+
      box("近 24 小时新闻情绪",'<div class="news-plot" id="news-hours" role="img" aria-label="按小时汇总的新闻情绪，明细在下方"></div>'+
        '<details><summary>查看每小时条数与分数</summary>'+hoursTable+'</details>'+
        note("按最新一条快讯所在小时向前取 24 小时。空白小时在本批样本中没有报道。"))+'</div>'+
      box("行业新闻热度",sectors.length ? '<div id="news-sectors" role="img" aria-label="按新闻条数排列的行业热度"></div>'+
        table(["行业","新闻数","情绪分","正面占比"],sectors.map(g=>[esc(g.name),String(g.count),fmt(g.sum/g.count,1),fmt(100*g.pos/g.count,1)+"%"]))+
        note("列出被至少两条快讯提及的行业，最多展示前 12 个。") : empty("本批样本没有被至少两条快讯同时提及的行业。"))+
      '<div class="two even">'+box("最正面的标题",headlines(stats.positive))+box("最负面的标题",headlines(stats.negative))+'</div>';
    if (hoursOpen) summary.querySelector("details").open = true;
    const mine = ++generation;
    nodes = {gauge:id("gauge"),hours:id("hours"),sectors:id("sectors")};
    renderNewsCharts(nodes,stats,()=>isCurrent() && mine===generation).catch(()=>{
      if (isCurrent() && mine===generation) id("gauge").textContent="图表暂时无法显示，分数及明细见本页。";
    });
    stockResult();
  }

  function schedule() {
    clearTimeout(timer);
    if (!closed && isCurrent() && !document.hidden && !busy) {
      timer = setTimeout(()=>load(false), Math.max(0, nextSync - Date.now()));
    }
  }

  async function load(manual) {
    if (busy || closed || !isCurrent()) return;
    clearTimeout(timer);
    busy = true;
    nextSync = Date.now() + syncPeriod;
    refresh.disabled = true;
    if (manual || !edition) status.textContent = manual ? "正在刷新快讯…" : "正在读取已归档的新闻样本…";
    try {
      const data = await api("/api/news",35000,manual?{body:JSON.stringify({refresh:true})}:{});
      if (closed || !isCurrent()) return;
      const changed = !edition || (data.checked !== edition.checked &&
        JSON.stringify(data.articles) !== JSON.stringify(edition.articles));
      edition = data;
      const first = data.articles[0].time, last = data.articles.at(-1).time;
      status.textContent = (data.notice ? data.notice+" 正在显示上次成功的样本。 " : "")+
        "样本覆盖 "+last+" 至 "+first+" · 采集于 "+data.checked;
      if (changed) paint();
    } catch (error) {
      if (!closed && isCurrent()) status.textContent = String(error.message)+" "+(edition?"保留上次样本，可再次刷新。":"可点击「刷新新闻」重试。");
    } finally {
      busy = false;
      if (!closed && isCurrent()) refresh.disabled=false;
      schedule();
    }
  }
  refresh.onclick=()=>load(true);
  document.addEventListener("visibilitychange", schedule);
  load(false);
  return ()=>{
    closed = true;
    generation++;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", schedule);
    clearNewsCharts(nodes);
  };
}
