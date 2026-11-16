/** Coggan's 7 power zones, as % of FTP: [from %, short name, name, colour]. */
export const POWER_ZONES: [number, string, string, string][] = [
  [0, 'Z1', 'Recuperación', '#7c8f9c'],
  [56, 'Z2', 'Resistencia', '#7fb6ff'],
  [76, 'Z3', 'Tempo', '#6ce8af'],
  [91, 'Z4', 'Umbral', '#e9d27a'],
  [106, 'Z5', 'VO2 máx', '#f2a65a'],
  [121, 'Z6', 'Anaeróbica', '#ef7b6b'],
  [151, 'Z7', 'Neuromuscular', '#d36bd8'],
];

export type Zone = { short: string; name: string; color: string; pct: number; from: number; to: number | null };

/** The zone of ``watts`` for ``ftp``; null without both. */
export function powerZone(watts: number | null | undefined, ftp: number | null | undefined): Zone | null {
  if (watts == null || !ftp) return null;
  const pct = (watts / ftp) * 100;
  const i = POWER_ZONES.map(([from]) => from).filter((from) => pct >= from).length - 1;
  const [from, short, name, color] = POWER_ZONES[Math.max(0, i)];
  const next = POWER_ZONES[i + 1];
  return { short, name, color, pct, from, to: next ? next[0] - 1 : null };
}
