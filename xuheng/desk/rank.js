/** @template {Array<string|number|null>} T @param {T[]} rows @param {1|2} key @returns {T[]} */
export function rank(rows, key) {
  return rows.filter(row => Number.isFinite(row[key])).sort((a, b) => {
    const difference = Number(a[key]) - Number(b[key]);
    return (key === 2 ? difference : -difference) || String(a[0]).localeCompare(String(b[0]));
  });
}
