import {esc} from "./lab.js";

export function searchField(id,placeholder){
 return '<div class="searchbox"><input class="entry portfolio-input" id="'+id+'" type="search" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="'+id+'-hits" aria-label="'+esc(placeholder)+'" placeholder="'+esc(placeholder)+'" autocomplete="off"><div class="matches" id="'+id+'-hits" role="listbox" aria-label="匹配证券" hidden></div></div>';
}
export function bindSearch(id,find,choose){
 const input=document.getElementById(id),list=document.getElementById(id+"-hits");if(!input||!list)return;
 let rows=[],active=-1;
 const close=()=>{rows=[];active=-1;list.hidden=true;list.replaceChildren();input.setAttribute("aria-expanded","false");input.removeAttribute("aria-activedescendant");};
 const mark=n=>{
   active=n;Array.from(list.querySelectorAll("[role=option]")).forEach((b,i)=>b.setAttribute("aria-selected",String(i===n)));
   const option=list.children[n];if(option){input.setAttribute("aria-activedescendant",option.id);option.scrollIntoView({block:"nearest"});}
 };
 const show=()=>{const q=input.value.trim().toLowerCase();close();if(!q)return;rows=find(q).slice(0,12);
   list.hidden=false;input.setAttribute("aria-expanded","true");
   list.innerHTML=rows.length?rows.map((r,i)=>'<button type="button" tabindex="-1" role="option" aria-selected="false" id="'+id+'-hit-'+i+'" data-code="'+esc(r[0])+'">'+esc(r[1])+' · '+esc(r[0])+(r[2]?' <small>'+esc(r[2])+'</small>':'')+'</button>').join(""):'<small role="status">未找到匹配证券</small>';
 };
 const select=n=>{const r=rows[n];if(!r)return;input.value="";close();choose(r[0]);};
 input.oninput=show;
 input.onfocus=()=>{if(input.value.trim())show();};
 input.onkeydown=e=>{
   if(e.isComposing||e.keyCode===229)return;
   if(e.key==="Escape"){if(!list.hidden){e.preventDefault();close();}return;}
   if(e.key==="ArrowDown"||e.key==="ArrowUp"){
     if(list.hidden)show();if(!rows.length)return;e.preventDefault();
     mark(active<0?(e.key==="ArrowDown"?0:rows.length-1):Math.max(0,Math.min(rows.length-1,active+(e.key==="ArrowDown"?1:-1))));return;
   }
   if(e.key==="Enter"&&!list.hidden&&rows.length){e.preventDefault();select(active<0?0:active);}
 };
 list.onmousedown=e=>e.preventDefault();
 list.onclick=e=>{const b=e.target.closest("[role=option]");if(b)select(rows.findIndex(r=>r[0]===b.dataset.code));};
 input.onblur=()=>close();
}
