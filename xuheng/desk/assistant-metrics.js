// The research assistant calls this adapter alongside the stock page's calculation modules.
function assistantStockData(raw) {
  const p = JSON.parse(raw);
  const bars = rows => rows.map(([day, open, high, low, close, pre_close, pct, volume, amount]) =>
    ({day, open, high, low, close, pre_close, pct, volume, amount}));
  const stock = bars(p.bars);
  const market = p.launch ? bars(p.index).filter(b => b.day >= p.launch) : [];
  const percent = value => Number.isFinite(value) ? value * 100 : null;
  if (p.mode === "beta" || p.mode === "beta_history") {
    const {latest, points, pairs} = rollingBeta(stock, market);
    if (p.mode === "beta_history") return JSON.stringify(points);
    const reason = !p.launch ? "基准缺少发布日期" : p.marketStatus === "denied" ? "基准日线权限不足" :
      p.stockStatus === "denied" ? "个股日线权限不足" : !latest ? "有效配对不足 120 日" :
      latest.value === null ? "基准收益方差不足" : null;
    return JSON.stringify([[latest?.start, latest?.end, latest ? latest.observations.length : pairs,
      latest?.value, latest?.correlation, latest ? latest.covariance * 10000 : null,
      latest ? latest.variance * 10000 : null, reason]]);
  }
  const prices = researchPrices(stock.filter(b => b.day >= p.listed && b.day <= p.last), p.calendar);
  if (!prices.end) return "[]";
  const {end} = prices;
  const profile = valuationProfile(prices, p.valuations, p.quote);
  const active = p.active && end.d === p.asOf && (p.historical ||
    (Number.isFinite(p.quote?.close) && Math.abs(p.quote.close - end.close) < .005));
  const result = assessment(prices, profile), risk = yearRisk(prices);
  const history = signalHistory(prices, profile, result);
  const sim = active ? simulateYear(prices, p.code) : null;
  const rating = signalRating(result, history, sim, prices, active);
  const relative = active && p.totalLaunch ? relativeHistory(history, bars(p.total), p.totalLaunch) : null;
  const outlook = relative?.direction == null ? null :
    relative.direction > 0 ? "相对偏强" : relative.direction < 0 ? "相对偏弱" : "相对持平";
  const recent = stockWindows(stock);
  const strength = relativeStrength(recent, {launch:p.launch,bars:market});
  return JSON.stringify([[end.d, end.close, ...end.ma, result.trend, rating.label, result.basis,
    profile.metrics.pe.value, percent(profile.metrics.pe.position), profile.metrics.pb.value, percent(profile.metrics.pb.position),
    result.low, result.high, prices.atr, prices.stop, percent(rating.cap), percent(risk?.vol), percent(risk?.worst),
    percent(recent.growth), percent(strength.difference), percent(recent.turnover?.change),
    percent(sim?.win), percent(sim?.quantiles[2]), sim?.n, outlook, relative?.n, relative?.wins,
    percent(relative?.median), percent(sim?.quantiles[0]), percent(sim?.quantiles[1]),
    percent(sim?.quantiles[3]), percent(sim?.quantiles[4]), percent(sim?.dd),
    result.n, result.from, result.to, relative?.nonoverlap, active ? null : "末次成交或历史回顾"]]);
}
