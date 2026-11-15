import {ready, request} from "./bridge.js";
import {restoreSettings} from "./restore.js";
await ready.then(({version})=>restoreSettings(version));
await import("./desk.js");
let addressTimer;
addEventListener("hashchange", () => {
  // The market/series request may already have synchronized this route. A local
  // page such as the portfolio form still needs a shareable host URL of its own.
  clearTimeout(addressTimer);
  addressTimer=setTimeout(()=>request("/route", null, 20000).catch(()=>{}),150);
});
