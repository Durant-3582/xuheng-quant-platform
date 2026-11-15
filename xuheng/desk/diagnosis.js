// Keep the start close separate from the following 20 returns, including at IPO.
export function stockWindows(bars) {
  const sessions = bars.filter(b => Number.isFinite(b.close) && b.close > 0 &&
    Number.isFinite(b.volume) && b.volume > 0).slice(-21);
  const days = sessions.slice(-20);
  const anchor = sessions.length === 21 ? sessions[0] : null;
  // A recorded zero-volume day can be skipped. An incomplete quote inside
  // the window cannot be treated as a suspension or silently dropped.
  const incomplete = sessions.length ? bars.filter(b => b.day > sessions[0].day && b.day <= sessions.at(-1).day &&
    (!Number.isFinite(b.volume) || b.volume < 0 || b.volume > 0 && !(Number.isFinite(b.close) && b.close > 0))) : [];
  const invalidPrices = [...incomplete,...days.filter(b => !(Number.isFinite(b.pre_close) && b.pre_close > 0))];
  let growth = null;
  if (anchor && !invalidPrices.length) {
    growth = days.reduce((value, b) => value * (b.close / b.pre_close), 1) - 1;
  }
  const invalidAmounts = [...incomplete.filter(b => b.day >= days[0].day),...days.filter(b => !Number.isFinite(b.amount) || b.amount < 0)];
  let turnover = null;
  if (days.length === 20 && !invalidAmounts.length) {
    const sum = rows => rows.reduce((total, b) => total + b.amount, 0);
    const five = sum(days.slice(-5)) / 5, twenty = sum(days) / 20;
    turnover = {five, twenty, change:twenty > 0 ? five / twenty - 1 : null};
  }
  return {sessions, days, anchor, end:days.at(-1), growth, turnover, invalidAmounts, invalidPrices};
}

// Compare the same two closes on the calendar. The index continues to trade
// during stock suspensions. Exclude backfilled index prices before publication.
export function relativeStrength(stock, market) {
  if (stock.growth === null) return {reason:"个股累计收益的样本不足。"};
  if (!market.launch) return {reason:"基准缺少可核对的发布日期。"};
  if (stock.anchor.day < market.launch) return {reason:"区间起点早于基准发布日期 " + market.launch + "。"};
  const start = market.bars.find(b => b.day === stock.anchor.day);
  const end = market.bars.find(b => b.day === stock.end.day);
  if (!(start?.close > 0 && end?.close > 0)) return {reason:"基准在个股区间的起点或终点缺少有效收盘价。"};
  const growth = end.close / start.close - 1;
  return {start, end, growth, difference:stock.growth - growth};
}
