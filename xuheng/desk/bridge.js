import {ownsAddress,startNavigation} from "./navigation.js";
// Each browser tab owns a queue. Streamlit widgets deliver their latest value, so
// the next request can only be sent after Python has answered the preceding one.
const hostOrigin = document.referrer ? new URL(document.referrer).origin : location.origin;
const post = (type, fields) => parent.postMessage({isStreamlitMessage:true, type, ...fields}, hostOrigin);
// Streamlit normally removes a component's scrollbar because its height follows
// its contents. This component occupies the viewport, so it owns page scrolling.
try {
  if (window.frameElement) window.frameElement.setAttribute("scrolling","auto");
  parent.document.documentElement.lang="zh-CN";
  parent.document.documentElement.setAttribute("translate","no");
} catch { /* The child document already declares its language. */ }
const queue = [];
const nonce = crypto.randomUUID();
let sequence = 0, active, started = false, release;
let resolveReady;
export const ready = new Promise(resolve => { resolveReady = resolve; });

function sendNext() {
  if (!started || active || !queue.length) return;
  active = queue.shift();
  const task = active;
  task.timer = setTimeout(() => {
    if (active !== task) return;
    active = undefined;
    task.reject(new Error("读取数据超时，请重试。"));
    sendNext();
  }, task.timeout);
  post("streamlit:setComponentValue", {dataType:"json", value:{
    id:task.id, path:task.path, body:task.body, route:location.hash.slice(1) || "overview",
    clientRouting:ownsAddress, gzip:typeof DecompressionStream === "function"
  }});
}

export function request(path, body, timeout) {
  return new Promise((resolve, reject) => {
    queue.push({id:nonce + "-" + (++sequence), path, body, timeout, resolve, reject});
    sendNext();
  });
}

async function unpack(reply) {
  if (!reply.gz) return reply.data;
  const bytes=Uint8Array.from(atob(reply.gz), c=>c.charCodeAt(0));
  const body=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(body).json();
}

addEventListener("message", async event => {
  if (event.source !== parent || event.origin !== hostOrigin || event.data?.type !== "streamlit:render") return;
  const {reply, initialRoute, version} = event.data.args;
  if (!started) {
    started = true;
    release = version.id;
    const route = initialRoute || "overview";
    startNavigation(route);
    resolveReady({route,version,newsPlots:event.data.args.newsPlots});
    sendNext();
  } else if (version.id !== release) {
    location.reload();
    return;
  }
  const task = active;
  if (!task || reply?.id !== task.id || task.settling) return;
  task.settling = true;
  clearTimeout(task.timer);
  try {
    if (reply.error) throw Object.assign(new Error(reply.error), {code:reply.code});
    task.resolve(await unpack(reply));
  } catch(error) {
    task.reject(error);
  } finally {
    active = undefined;
    sendNext();
  }
});
post("streamlit:componentReady", {apiVersion:1});
post("streamlit:setFrameHeight", {height:700});
