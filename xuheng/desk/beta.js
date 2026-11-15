// Each return covers the same single session for both series. Skip the first day back after a suspension.
export function rollingBeta(stock, index, size = 120) {
  const market = new Map();
  for (let i = 1; i < index.length; i++) {
    const bar = index[i], prior = index[i-1];
    const reference = bar.pre_close ?? prior.close;
    if (bar.close > 0 && reference > 0) market.set(bar.day, [prior.day, bar.close / reference - 1]);
  }
  const window = [], points = [];
  let sx = 0, sy = 0, sxx = 0, sxy = 0, pairs = 0;
  for (let i = 1; i < stock.length; i++) {
    const bar = stock[i], match = market.get(bar.day);
    if (!match || stock[i-1].day !== match[0] || !(bar.close > 0 && bar.pre_close > 0) || !(bar.volume>0 && stock[i-1].volume>0)) continue;
    const x = match[1], y = bar.close / bar.pre_close - 1;
    pairs++;
    window.push([x,y]);
    sx += x; sy += y; sxx += x*x; sxy += x*y;
    if (window.length > size) {
      const [oldX,oldY] = window.shift();
      sx -= oldX; sy -= oldY; sxx -= oldX*oldX; sxy -= oldX*oldY;
    }
    if (window.length < size) continue;
    const variance = sxx - sx*sx/size;
    if (variance > 1e-12 * Math.max(sxx, 1e-10)) {
      points.push([bar.day.replaceAll("-", ""), (sxy - sx*sy/size) / variance]);
    }
  }
  return {pairs, points};
}
