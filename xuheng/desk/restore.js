// Import visitor preferences from the first independent Streamlit interface once.
export function restoreSettings({id,catalog,day,sample}) {
  function copy(storage, key, value) {
    if (storage.getItem(key) === null && value !== undefined) storage.setItem(key, JSON.stringify(value));
  }
  try {
    const read = (s,k) => JSON.parse(s.getItem(k));
    const releaseKey="xuheng.desk.release";
    const priorRelease=sessionStorage.getItem(releaseKey);
    const studyKey="xuheng.portfolio-comparison.v2";
    const study=read(sessionStorage,studyKey);
    if(study?.draft && ((priorRelease && priorRelease!==id) || (study.assessment?.day && study.assessment.day!==day))){
      sessionStorage.setItem(studyKey,JSON.stringify({draft:study.draft}));
    }
    sessionStorage.setItem(releaseKey,id);
    const roster = read(localStorage,"xuheng.independent.holdings.v1");
    if (Array.isArray(roster)) {
      copy(localStorage,"xuheng.positions.v1",roster);
      copy(localStorage,"xuheng.position-weights-auto.v1",read(localStorage,"xuheng.independent.holdings.v1.equal"));
    }
    const filters=read(localStorage,"xuheng.independent.filters.v1");
    if (Array.isArray(filters)) copy(localStorage,"xuheng.filters.v1",filters.filter(r=>r?.name).map(r=>({
      label:r.name,factorKey:r.factor,factorVenue:r.market,factorSector:r.sector==="全部行业"?"":r.sector
    })));
    const previous=read(sessionStorage,"xuheng.independent.study.v1");
    const active=previous?.version===catalog;
    if (active) copy(sessionStorage,"xuheng.portfolio-seen.v2",previous.seen);
    if (!active && !sample) return;
    const config=active ? previous.inputs || {} : {};
    const val=(prefix,field,fallback)=>config["cfg_"+prefix+"_"+field]??fallback;
    const compact=(s)=>s?.replaceAll("-","");
    function candidate(prefix,manual,i=0) {
      const get=(field,fallback)=>val(prefix,field,fallback);
      const frequency=get(manual?"freqcustom":"freqmodel", manual?"hold":"months");
      return {model:manual?"manual":get("model","mom"),count:get("count",10*(i+1)),
        weight:get(manual?"manw":"sysw",manual?(i===0?"equal":"tb"):"equal"),
        freq:{hold:"hold",days:"custom",months:"1",quarter:"3",half:"6"}[frequency]||"1",
        days:String(get(manual?"days":"daysmodel",10)), weights:get("rankweights","")};
    }
    if (active && Object.keys(config).some(k=>k.startsWith("cfg_range_"))) {
      const m=val("range","model","mom")==="manual", r=candidate("range",m);
      const interval=r.freq==="custom"?Number(r.days):r.freq==="hold"?1:Number(r.freq);
      copy(sessionStorage,"xuheng.portfolio-range.v2",{draft:{
        model:r.model,count:r.count,weighting:r.weight,interval,intervalUnit:r.freq==="hold"?"hold":r.freq==="custom"?"days":"months",
        bench:val("range","benchmark","000300.SH"),fee:val("range","fee",10),controlModel:val("range","ctrl","mom"),
        exchange:val("range","exchange",""),rankWeightText:r.weights,weights:[],symbols:[]
      },from:compact(val("range","a")),to:compact(val("range","b")),
      cadences:{[m?"manual":"factor"]:{freq:r.freq,days:r.days}},manualWeight:val("range","manw","manual")});
    }
    const get=(field,fallback)=>val("study",field,fallback);
    const common={source:get("source","all")==="manual"?"manual":"factor",exchange:get("exchange",""),controlModel:get("ctrl","mom"),
      bench:get("benchmark","000300.SH"),fee:get("fee",10),
      trainFrom:compact(get("trainA",sample?"20230101":"20100101")),trainTo:compact(get("trainB",sample?"20241231":"20191231")),
      testFrom:compact(get("testA",sample?"20250101":"20200101")),testTo:compact(get("testB",day))};
    const rows=(n,manual)=>Array.from({length:Math.min(8,Math.max(2,n))},(_,i)=>candidate("study_"+i,manual,i));
    const draft={common,criterion:get("criterion","return"),factor:rows(get("candidates",2),false),manual:rows(get("candidatesManual",2),true)};
    const state={draft};
    if (active && previous.locked) state.restoreLock={roster:previous.lockedRoster||[]};
    copy(sessionStorage,"xuheng.portfolio-comparison.v2",state);
  } catch { /* Storage may be unavailable in a private or embedded browser. */ }
}
