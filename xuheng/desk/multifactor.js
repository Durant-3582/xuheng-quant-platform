import {esc,fmt} from "./lab.js";

export const factors={mom:"60 日动量",vol:"20 日低波动",pb:"低市净率",roe:"最近年报 ROE",pe:"低滚动市盈率",turn:"当日高换手"};
export const defaults={mom:25,vol:0,pb:40,roe:35,pe:0,turn:0};
export const currentRule=w=>Object.keys(factors).filter(k=>w?.[k]>0).map(k=>factors[k]+" "+w[k]+"%").join(" · ");
export const validMix=w=>Object.keys(factors).every(k=>Number.isFinite(w[k])&&w[k]>=0&&w[k]<=100)
  &&Math.abs(Object.values(w).reduce((a,b)=>a+b,0)-100)<0.005;

export function weightInputs(prefix,w) {
  return '<div class="study-weights">'+Object.entries(factors).map(([k,title])=>'<label>'+esc(title)+'（%） <input type="number" min="0" max="100" step="0.01" required id="'+prefix+k+'" data-mix-factor="'+k+'" value="'+esc(w[k]??"")+'"></label>').join("")+'</div>';
}
export function readMix(root){
  return Object.fromEntries(Array.from(root.querySelectorAll("[data-mix-factor]"),n=>[n.dataset.mixFactor,n.valueAsNumber]));
}
export function totalText(w) {
  const total=Object.values(w).reduce((a,b)=>a+b,0);
  return (Number.isFinite(total)?"合计 "+fmt(total,2)+"%":"请填写所有因子权重")+(validMix(w)?"":" · 合计须为 100%");
}
const handoff="xuheng.pending-factor-rule.v1";
let pending;
export function sendRule(weights,venue) {
  pending={weights:{...weights},venue};
  try{sessionStorage.setItem(handoff,JSON.stringify(pending));}catch{}
}
export function takeRule(){
  let value=pending;
  try{value??=JSON.parse(sessionStorage.getItem(handoff));sessionStorage.removeItem(handoff);}catch{}
  pending=null;
  return value?.weights&&validMix(value.weights)&&["","SH","SZ","BJ"].includes(value.venue)?value:null;
}
