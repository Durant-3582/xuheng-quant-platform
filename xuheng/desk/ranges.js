import {select} from "./lab.js";

export function rangeControl(id, label, presets, state) {
  return select(id, label, [...presets, ["custom","自定义交易日数"]], state.custom ? "custom" : state.days)
    + '<span class="custom-days" id="' + id + '-custom"' + (state.custom ? "" : " hidden") + '>'
    + '<label>交易日数 <input id="' + id + '-days" type="number" min="1" step="1" required value="' + (state.lastCustom || state.days || 90) + '"></label>'
    + '<button type="button" class="quiet" id="' + id + '-apply">应用</button></span>';
}

export function bindRange(id, state, refresh) {
  const field = document.getElementById(id), group = document.getElementById(id+"-custom");
  const input = document.getElementById(id+"-days");
  field.onchange = () => {
    state.custom = field.value === "custom";
    group.hidden = !state.custom;
    if (state.custom) { input.focus(); input.select(); return; }
    state.days = Number(field.value);
    refresh();
  };
  function apply() {
    const days = input.valueAsNumber;
    if (!Number.isSafeInteger(days) || days < 1) {
      input.setCustomValidity("请输入大于零的整数交易日数。");
      input.reportValidity();
      return;
    }
    state.days = state.lastCustom = days;
    refresh();
  }
  input.oninput = () => input.setCustomValidity("");
  input.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); apply(); } };
  document.getElementById(id+"-apply").onclick = apply;
}
