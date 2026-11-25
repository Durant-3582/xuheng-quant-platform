// Exercise the production evidence renderer with mixed records and untrusted links.
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const dataUrl = code => "data:text/javascript;base64,"+Buffer.from(code).toString("base64");
const lab = (await readFile(new URL("../xuheng/desk/lab.js",import.meta.url),"utf8"))
  .replace(/^import .*;\n/gm, "").replace(/^export \{rank\};\n/m, "");
const source = (await readFile(new URL("../xuheng/desk/assistant.js",import.meta.url),"utf8"))
  .replace('"./lab.js"',JSON.stringify(dataUrl(lab)));
const {sourceLink,sourceView,visibleAnswer,turnView} = await import(dataUrl(source));
const cases = JSON.parse(await readFile(new URL("./assistant_protocol_cases.json",import.meta.url),"utf8"));
for (const text of cases.blocked) {
  assert.notEqual(visibleAnswer(text), text);
  const rendered = turnView({question:"继续查询",answer:text,evidence:[{
    source:"本站数据库",endpoint:"query_site",scope:"已查询",rows:[{值:2}],note:""}]});
  assert.ok(!rendered.includes("DSML") && !rendered.includes("tool_call"));
  assert.ok(rendered.includes("查询格式错误") && rendered.includes("查看数据依据（1）"));
}
for (const text of cases.allowed) assert.equal(visibleAnswer(text),text);

for (const url of ["javascript:alert(1)","data:text/html,bad","https://user:secret@example.com",null])
  assert.ok(!sourceLink(url).includes("<a "));
const good = sourceLink("https://www.sse.com.cn/notice?x=1&y=2");
assert.ok(good.includes('rel="noopener noreferrer"') && good.includes('target="_blank"'));
assert.ok(good.includes("x=1&amp;y=2"));
assert.ok(!sourceLink('<img src=x onerror=alert(1)>').includes("<img"));
const view = sourceView({source:"外部资料 <script>alert(1)</script>",endpoint:"search_web",scope:"核验",
  rows:[{"标题":"公告","链接":"https://example.com/notice"},{"新增字段":{"值":2},"标题":"<img src=x>"}],note:"<script>bad</script>"});
assert.ok(view.includes("新增字段") && view.includes('&quot;值&quot;:2'));
assert.ok(view.includes("查看原文") && !view.includes("[object Object]"));
assert.ok(!view.includes("<script>") && !view.includes("<img"));
assert.ok(sourceView({source:"查询状态",endpoint:"query_site",scope:"无结果",rows:[],note:"未查到"}).includes("未查到"));
console.log("PASS: external source links, mixed evidence columns, nested values, empty results and HTML escaping.");
