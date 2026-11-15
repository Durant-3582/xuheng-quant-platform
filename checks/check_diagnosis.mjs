import assert from "node:assert/strict";
import {stockWindows, relativeStrength} from "../xuheng/desk/diagnosis.js";
import {rollingBeta} from "../xuheng/desk/beta.js";

const closeTo = (a,b) => assert.ok(Math.abs(a-b) < 1e-9, a+" differs from "+b);
// A deterministic common trading calendar for split, IPO and suspension cases.
const dates=[];
for(let d=new Date("2024-01-01T00:00:00Z");dates.length<180;d.setUTCDate(d.getUTCDate()+1)){
  if(d.getUTCDay()%6!==0) dates.push(d.toISOString().slice(0,10));
}
let equity=50, index=1000;
const shares=[], benchmark=[];
for(let i=0;i<dates.length;i++){
  const marketReturn = i%2 ? 0.01 : -0.004;
  const stockReturn = 0.0008+1.5*marketReturn;
  const reference = i===170 ? equity/2 : equity;
  shares.push({day:dates[i],pre_close:reference,close:reference*(1+stockReturn),volume:10,amount:100+i});
  benchmark.push({day:dates[i],pre_close:index,close:index*(1+marketReturn)});
  equity=shares.at(-1).close;
  index=benchmark.at(-1).close;
}
const s=stockWindows(shares), market={launch:dates[0],bars:benchmark};
const stockReturn=(1.0158*0.9948)**10-1;
closeTo(s.growth,stockReturn);
assert.ok(shares.at(-1).close/s.anchor.close-1 < 0 && s.growth > 0);
closeTo(s.turnover.five,277);
closeTo(s.turnover.twenty,269.5);
const rel=relativeStrength(s,market);
closeTo(rel.growth,(1.01*0.996)**10-1);
closeTo(rel.difference,stockReturn-rel.growth);
const short=stockWindows(shares.slice(0,4));
assert.equal(short.growth,null);
assert.equal(short.turnover,null);
assert.equal(stockWindows(shares.slice(0,20)).growth,null);
assert.ok(stockWindows(shares.slice(0,20)).turnover);
assert.equal(stockWindows([]).end,undefined);
assert.ok(relativeStrength(s,{...market,launch:s.end.day}).reason);
assert.ok(relativeStrength(s,{...market,bars:benchmark.slice(0,-1)}).reason);
const damaged=shares.map((b,i)=>i===174?{...b,pre_close:null}:b);
assert.equal(stockWindows(damaged).growth,null);
assert.ok(stockWindows(damaged).turnover);
assert.equal(stockWindows(shares.map((b,i)=>i===179?{...b,amount:null}:b)).turnover,null);
const incomplete=stockWindows(shares.map((b,i)=>i===176?{...b,volume:null}:b));
assert.equal(incomplete.growth,null);
assert.equal(incomplete.turnover,null);
assert.equal(stockWindows(shares.map(b=>({...b,amount:0}))).turnover.change,null);
const paused=shares.filter((_,i)=>i!==169);
const pausedWindow=stockWindows(paused);
assert.equal(pausedWindow.anchor.day,dates[158]);
closeTo(relativeStrength(pausedWindow,market).growth,benchmark.at(-1).close/benchmark[158].close-1);
const ended=stockWindows([...shares,{...shares.at(-1),day:"2025-01-01",volume:0}]);
assert.equal(ended.end.day,s.end.day);
const beta=rollingBeta(shares,benchmark);
assert.equal(beta.latest.observations.length,120);
assert.equal(beta.latest.start,dates.at(-120));
assert.equal(beta.latest.end,s.end.day);
closeTo(beta.latest.value,1.5);
closeTo(beta.latest.covariance/beta.latest.variance,1.5);
assert.equal(beta.latest.value,beta.points.at(-1)[1]);
const skip=rollingBeta(paused,benchmark);
assert.equal(skip.pairs,beta.pairs-2);
assert.ok(!skip.latest.observations.some(row=>row[2]===dates[170]));
const constant=rollingBeta(shares,benchmark.map(b=>({...b,pre_close:100,close:100})));
assert.equal(constant.latest.value,null);
assert.equal(constant.points.length,0);
assert.equal(rollingBeta(shares.slice(-120),benchmark).latest,null);
console.log("PASS: 20-session returns, corporate actions, matched endpoints, turnover, short histories, suspensions and 120-pair Beta evidence.");
