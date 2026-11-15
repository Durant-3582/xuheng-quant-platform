import {api,box,date,esc,note,table,title} from "./lab.js";

const call = body => api("/api/assistant", 240000, {body:JSON.stringify(body)});
let turns = [], draft = "", pending = false, failure = "", retryId, ready = false, loaded = false;

function sourceView(item) {
  const fields = Object.keys(item.rows[0] || {});
  const records = item.rows.map(row => fields.map(field => esc(row[field] ?? "缺失")));
  return '<section class="answer-source"><h3>'+esc(item.source)+' · '+esc(item.endpoint)+'</h3>'+
    '<p>'+esc(item.scope)+'</p>'+(records.length ? table(fields, records) : note("本次查询没有数据行。"))+
    (item.note ? note(item.note) : "")+'</section>';
}

function turnView(turn) {
  return '<article class="answer-turn"><h2>'+esc(turn.question)+'</h2><p class="answer-text">'+esc(turn.answer)+'</p>'+
    (turn.evidence.length ? '<details><summary>查看数据依据（'+turn.evidence.length+'）</summary>'+
      turn.evidence.map(sourceView).join("")+'</details>' : "")+'</article>';
}

export async function assistantPage({panel,day,current}) {
  const examples = ["贵州茅台最近一次收盘价是多少？",
    date(day)+"，沪深300收盘多少点？","最近有多少只 A 股站上了 200 日均线？"];
  const head = title("研究问答","用 DeepSeek V4.1 Flash 查询 A 股行情、估值和财报，或核对序衡的市场宽度与自选组合回测。");
  function render(focus=false) {
    if (!current()) return;
    const disabled = pending || !loaded || !ready;
    panel.innerHTML = head+'<div id="research-chat"><div id="answer-list">'+turns.map(turnView).join("")+'</div>'+
      box("研究问题",'<form id="research-chat-form"><label class="chat-label" for="research-question">问题或追问</label>'+
        '<textarea id="research-question" rows="3" maxlength="900" placeholder="输入股票、指标和日期…"></textarea>'+
        '<div class="actions"><button class="primary" type="submit" '+(disabled?'disabled':'')+'>发送问题</button>'+
        (turns.length?'<button class="quiet" type="button" id="clear-chat" '+(pending?'disabled':'')+'>清空对话</button>':'')+'</div></form>'+
        '<p class="chat-status" role="status"></p>'+
        (!turns.length?'<div class="chat-examples">'+examples.map((q,i)=>'<button class="quiet" data-example="'+i+'" type="button">'+esc(q)+'</button>').join("")+'</div>':""))+'</div>';
    const input=panel.querySelector("textarea"), form=panel.querySelector("form");
    input.value=draft; input.readOnly=pending;
    const send=form.querySelector('[type="submit"]');
    send.disabled=disabled || !draft.trim();
    const status=panel.querySelector(".chat-status");
    status.textContent=pending ? "正在查询数据并核对回答…" : failure ||
      (!loaded ? "正在读取本次会话…" : !ready ? "问答所需的网站密钥尚未配置齐全。" : "");
    status.classList.toggle("error",!!failure);
    function setDraft() {draft=input.value;retryId=undefined;send.disabled=disabled || !draft.trim();}
    input.oninput=setDraft;
    input.onkeydown=e=>{if(e.key==="Enter" && (e.metaKey||e.ctrlKey) && !e.isComposing) {
      e.preventDefault(); if(!send.disabled)form.requestSubmit();
    }};
    for(const button of panel.querySelectorAll("[data-example]")) {
      button.disabled=pending;
      button.onclick=()=>{input.value=examples[Number(button.dataset.example)];setDraft();input.focus();};
    }
    form.onsubmit=async e=>{
      e.preventDefault();if(pending || !ready || !input.value.trim()) return;
      const question=input.value.trim(), turnId=retryId || crypto.randomUUID();
      draft=question;retryId=turnId;pending=true;failure="";render();
      try{
        const {turn}=await call({action:"ask",question,turnId});
        turns=[...turns.filter(t=>t.id!==turn.id),turn].slice(-12);draft="";retryId=undefined;
      }catch(err){failure=err.message;}
      finally{pending=false;render();}
    };
    const clear=panel.querySelector("#clear-chat");
    if(clear)clear.onclick=async()=>{
      if(pending)return;
      pending=true;failure="";render();
      try{const result=await call({action:"clear"});turns=result.turns;draft="";retryId=undefined;}
      catch(err){failure=err.message;}
      finally{pending=false;render(true);}
    };
    if(failure && !loaded) {
      const retry=document.createElement("button");retry.className="quiet";retry.textContent="重新连接";
      retry.onclick=()=>assistantPage({panel,day,current});status.after(retry);
    }
    if(focus) input.focus({preventScroll:true});
  }
  render();
  try{
    const state=await call({action:"history"});
    turns=state.turns;ready=state.ready;loaded=true;
    if(!pending)failure="";
  }catch(err){failure=err.message;loaded=false;}
  render();
}
