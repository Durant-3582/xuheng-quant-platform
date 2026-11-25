import {api,box,date,esc,note,table,title} from "./lab.js";

const call = body => api("/api/assistant", 360000, {body:JSON.stringify(body)});
let turns = [], draft = "", pending = "", failure = "", retryId, ready = false;
let access = "", challenge = "";

function applyAccess(reply) {
  access = reply?.access || "";
  challenge = reply?.challenge || "";
  if (access !== "unlocked") {
    turns = []; draft = ""; retryId = undefined; ready = false;
  } else if ("ready" in reply) ready = reply.ready;
  if (Array.isArray(reply?.turns) && access === "unlocked") turns = reply.turns;
  return access === "unlocked";
}

async function passwordProof(password, nonce) {
  if (!crypto.subtle) throw new Error("当前浏览器无法安全验证密码，请用 HTTPS 课程链接打开。");
  const encode = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encode.encode(password),
    {name:"HMAC",hash:"SHA-256"}, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encode.encode("xuheng-ai:"+nonce));
  return Array.from(new Uint8Array(signature), b=>b.toString(16).padStart(2,"0")).join("");
}

export function sourceView(item) {
  const fields = [...new Set(item.rows.flatMap(row => Object.keys(row)))];
  const records = item.rows.map(row => fields.map(field => field === "链接" ? sourceLink(row[field]) :
    esc(row[field] != null && typeof row[field] === "object" ? JSON.stringify(row[field]) : row[field] ?? "缺失")));
  return '<section class="answer-source"><h3>'+esc(item.source)+' · '+esc(item.endpoint)+'</h3>'+
    '<p>'+esc(item.scope)+'</p>'+(records.length ? table(fields, records) : note("本次查询没有数据行。"))+
    (item.note ? note(item.note) : "")+'</section>';
}

export function sourceLink(value) {
  try {
    const url = new URL(value);
    if (["https:","http:"].includes(url.protocol) && url.hostname && !url.username && !url.password)
      return '<a href="'+esc(url.href)+'" target="_blank" rel="noopener noreferrer">查看原文 · '+esc(url.hostname)+'</a>';
  } catch (_) {}
  return esc(value ?? "缺失");
}

export function visibleAnswer(value) {
  if (typeof value !== "string") return "未收到完整回答，请重新发送问题。";
  // Last rendering guard, including old session responses. This never executes
  // markup: query execution and recovery belong to the server tool-call loop.
  const normalized = value.normalize("NFKC").replace(/[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]/g, "")
    .replace(/&(?:amp;)*(?:lt|#0*60|#x0*3c);/gi, "<")
    .replace(/&(?:amp;)*(?:#0*124|#x0*7c|vert|VerticalLine);/gi, "|");
  return /<\s*\/?\s*(?:[|∣│]\s*)+(?:DSML\b|tool[▁_\s]*(?:calls?|sep)(?:\b|[▁_]))/i.test(normalized)
    ? "这条回答出现了查询格式错误，未形成完整结论。原有数据依据仍可查看，请重新发送问题。" : value;
}

export function turnView(turn) {
  return '<article class="answer-turn"><h2>'+esc(turn.question)+'</h2><p class="answer-text">'+esc(visibleAnswer(turn.answer))+'</p>'+
    (turn.evidence.length ? '<details><summary>查看数据依据（'+turn.evidence.length+'）</summary>'+
      turn.evidence.map(sourceView).join("")+'</details>' : note("本轮未查询数据"))+'</article>';
}

export async function assistantPage({panel,day,current}) {
  let checked = false, loadError = "";
  const examples = ["从全 A 股推荐 3 只值得研究的股票，说说你为什么选它们、各有什么风险。","对比贵州茅台与五粮液相对沪深300的120日滚动 Beta，列出窗口和数据依据。",
    date(day)+"，沪深300收盘多少点？","最近有多少只 A 股站上了 200 日均线？"];
  const head = title("研究问答","与 DeepSeek V4.1 Flash 讨论 A 股。优先查询本站和 Tushare，缺少的信息可检索外部资料，并查看数据依据与原文。");
  function render(focus=false) {
    if (!current()) return;
    if (!checked || !access) {
      panel.innerHTML = head+box("访问权限",note(loadError || (!checked ? "正在检查问答权限…" : "问答权限正在更新，请重新连接。"))+
        (loadError || checked ? '<button type="button" class="quiet" id="retry-chat">重新连接</button>' : ""));
      const retry=panel.querySelector("#retry-chat");
      if(retry)retry.onclick=()=>assistantPage({panel,day,current});
      return;
    }
    if (access !== "unlocked") {
      if(access !== "locked" || !challenge) {
        panel.innerHTML=head+box("研究问答暂未开放",note("管理员设置问答密码后，即可使用此功能。"));
        return;
      }
      panel.innerHTML=head+box("解锁研究问答",'<form id="chat-access"><label class="chat-label" for="chat-password">问答密码</label>'+
        '<div class="actions"><input type="password" id="chat-password" autocomplete="current-password" required>'+
        '<button type="submit" class="primary">解锁问答</button></div></form>'+
        '<p class="chat-status" role="status"></p>'+note("密码由课程负责人提供，仅用于研究问答。"));
      const form=panel.querySelector("#chat-access"), input=form.querySelector("input"), submit=form.querySelector("button");
      input.disabled=submit.disabled=!!pending;
      const status=panel.querySelector(".chat-status");
      status.textContent=pending==="unlock"?"正在验证密码…":failure;
      status.classList.toggle("error",!!failure);
      form.onsubmit=async e=>{
        e.preventDefault();if(pending||!input.value)return;
        const proof=passwordProof(input.value,challenge);
        input.value="";pending="unlock";failure="";render();
        try {
          const reply=await call({action:"unlock",proof:await proof});
          applyAccess(reply);failure=reply.message || "";
        } catch(err) {failure=err.message;}
        finally {pending="";render(true);}
      };
      if(focus)input.focus({preventScroll:true});
      return;
    }
    const disabled = pending || !ready;
    panel.innerHTML = head+'<div id="research-chat"><div id="answer-list">'+turns.map(turnView).join("")+'</div>'+
      box("研究问题",'<form id="research-chat-form"><label class="chat-label" for="research-question">问题或追问</label>'+
        '<textarea id="research-question" rows="3" maxlength="900" placeholder="向研究助手提问，例如：有哪些低估值的股票值得关注？"></textarea>'+
        '<div class="actions"><button class="primary" type="submit" '+(disabled?'disabled':'')+'>发送问题</button>'+
        (turns.length?'<button class="quiet" type="button" id="clear-chat" '+(pending?'disabled':'')+'>清空对话</button>':'')+
        '<button class="quiet" type="button" id="lock-chat" '+(pending?'disabled':'')+'>'+
        (turns.length || draft ? '锁定并清空本次对话' : '锁定问答')+'</button></div></form>'+
        '<p class="chat-status" role="status"></p>'+
        (!turns.length?'<div class="chat-examples">'+examples.map((q,i)=>'<button class="quiet" data-example="'+i+'" type="button">'+esc(q)+'</button>').join("")+'</div>':""))+'</div>';
    const input=panel.querySelector("textarea"), form=panel.querySelector("form");
    input.value=draft; input.readOnly=!!pending;
    const send=form.querySelector('[type="submit"]');
    send.disabled=disabled || !draft.trim();
    const status=panel.querySelector(".chat-status");
    status.textContent=({ask:"正在查询数据并核对回答…",clear:"正在清空对话…",lock:"正在锁定问答…"})[pending] ||
      failure || (!ready ? "问答所需的网站密钥尚未配置齐全。" : "");
    status.classList.toggle("error",!!failure);
    function setDraft() {draft=input.value;retryId=undefined;send.disabled=disabled || !draft.trim();}
    input.oninput=setDraft;
    input.onkeydown=e=>{if(e.key==="Enter" && (e.metaKey||e.ctrlKey) && !e.isComposing) {
      e.preventDefault(); if(!send.disabled)form.requestSubmit();
    }};
    for(const button of panel.querySelectorAll("[data-example]")) {
      button.disabled=!!pending;
      button.onclick=()=>{input.value=examples[Number(button.dataset.example)];setDraft();input.focus();};
    }
    form.onsubmit=async e=>{
      e.preventDefault();if(pending || !ready || !input.value.trim()) return;
      const question=input.value.trim(), turnId=retryId || crypto.randomUUID();
      draft=question;retryId=turnId;pending="ask";failure="";render();
      try{
        const reply=await call({action:"ask",question,turnId});
        if(!applyAccess(reply))return;
        const {turn}=reply;
        turns=[...turns.filter(t=>t.id!==turn.id),turn].slice(-12);draft="";retryId=undefined;
      }catch(err){failure=err.message;}
      finally{pending="";render();}
    };
    const reset=async action=>{
      if(pending)return;
      pending=action;failure="";render();
      try{applyAccess(await call({action}));draft="";retryId=undefined;}
      catch(err){failure=err.message;}
      finally{pending="";render(true);}
    };
    const clear=panel.querySelector("#clear-chat");
    if(clear)clear.onclick=()=>reset("clear");
    panel.querySelector("#lock-chat").onclick=()=>reset("lock");
    if(focus) input.focus({preventScroll:true});
  }
  render();
  try{
    const state=await call({action:"history"});
    if(!current())return;
    applyAccess(state);checked=true;
    if(!pending)failure="";
  }catch(err){loadError=err.message;}
  render();
}
