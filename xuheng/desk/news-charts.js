import {ready} from "./bridge.js";

let library;
function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (!library) library = ready.then(({newsPlots}) => new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = new URL("../" + encodeURIComponent(newsPlots) + "/plotly.min.js", import.meta.url);
    script.onload = () => window.Plotly ? resolve(window.Plotly) : reject(new Error());
    script.onerror = () => { script.remove(); reject(new Error()); };
    document.head.append(script);
  })).catch(error => { library = undefined; throw error; });
  return library;
}

const colors = {ink:"#192c2c", muted:"#506564", green:"#2e8066", red:"#a44751", line:"#e0e7e2"};
const layout = {
  autosize:true, paper_bgcolor:"white", plot_bgcolor:"white", showlegend:false,
  font:{family:"Inter, PingFang SC, Microsoft YaHei, sans-serif", size:12, color:colors.ink},
  margin:{l:44,r:14,t:12,b:40}
};
const config = {responsive:true, displaylogo:false, scrollZoom:false, displayModeBar:"hover"};

// Render into specific nodes. A delayed script load must not touch a newer page or edition.
export async function renderNewsCharts(nodes, stats, current) {
  const plotly = await loadPlotly();
  if (!current()) return;
  const jobs = [];
  jobs.push(plotly.newPlot(nodes.gauge, [{
    type:"indicator", mode:"gauge+number", value:stats.mean,
    number:{valueformat:".1f", suffix:" / 100", font:{size:28}},
    gauge:{axis:{range:[0,100], tickvals:[0,25,50,75,100]}, bar:{color:"#275e64",thickness:0.28},
      borderwidth:0, steps:[
        {range:[0,30],color:"#f1d6d9"}, {range:[30,45],color:"#f5e3d7"},
        {range:[45,60],color:"#e9efed"}, {range:[60,75],color:"#daede3"},
        {range:[75,100],color:"#c3e2d2"}]}
  }], {...layout, height:234, margin:{l:32,r:32,t:27,b:12}}, config));
  const hours = stats.hours.map(h => h.key.slice(5).replace("T"," ") + ":00");
  jobs.push(plotly.newPlot(nodes.hours, [{
    type:"bar", x:hours, y:stats.hours.map(h => h.count ? h.sum/h.count : null),
    customdata:stats.hours.map(h=>h.count),
    marker:{color:stats.hours.map(h=>h.sum >= 50*h.count ? colors.green : colors.red)},
    hovertemplate:"%{x}<br>情绪分 %{y:.1f}<br>快讯 %{customdata} 条<extra></extra>"
  }], {...layout, height:234, xaxis:{type:"category",tickvals:hours.filter((_,i)=>i%6===0 || i===23),
      ticktext:hours.filter((_,i)=>i%6===0 || i===23).map(x=>x.slice(-5)),fixedrange:true},
    yaxis:{range:[0,100],tickvals:[0,25,50,75,100],gridcolor:colors.line,fixedrange:true},
    shapes:[{type:"line",xref:"paper",x0:0,x1:1,y0:50,y1:50,line:{dash:"dot",color:colors.muted,width:1}}]
  }, config));
  if (stats.sectors.length) {
    const rows = stats.sectors.slice().reverse();
    jobs.push(plotly.newPlot(nodes.sectors,[{
      type:"bar",orientation:"h",x:rows.map(s=>s.count),y:rows.map(s=>s.name),
      customdata:rows.map(s=>s.sum/s.count),
      marker:{color:rows.map(s=>s.sum/s.count),colorscale:[[0,colors.red],[0.5,"#dedcc3"],[1,colors.green]],
        cmin:30,cmax:70,showscale:true,colorbar:{title:{text:"情绪分"},thickness:10,len:0.8}},
      hovertemplate:"%{y}<br>快讯 %{x} 条<br>情绪分 %{customdata:.1f}<extra></extra>"
    }], {...layout,height:Math.max(210,rows.length*25+65),margin:{l:76,r:45,t:6,b:42},
      xaxis:{title:{text:"快讯条数"},rangemode:"tozero",gridcolor:colors.line,fixedrange:true},
      yaxis:{type:"category",fixedrange:true}}, config));
  }
  await Promise.all(jobs);
}

export function clearNewsCharts(nodes) {
  if (window.Plotly && nodes) for (const node of Object.values(nodes)) {
    if (node && node.data) window.Plotly.purge(node);
  }
}
