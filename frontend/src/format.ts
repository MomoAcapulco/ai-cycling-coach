export const fmt = (n: number | null | undefined, decimals = 0): string =>
  n == null || !Number.isFinite(n)
    ? '—'
    : n.toLocaleString('es-ES', { maximumFractionDigits: decimals, minimumFractionDigits: decimals });

/** mm:ss, or h:mm:ss from one hour. */
export const clock = (seconds: number | null | undefined): string => {
  const v = Math.floor(Math.max(0, seconds ?? 0));
  const h = Math.floor(v / 3600);
  const m = Math.floor((v % 3600) / 60);
  const s = String(v % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${String(m).padStart(2, '0')}:${s}`;
};

export const average = (xs: number[]): number | null => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

export const bytes = (n: number): string =>
  n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${fmt(n / 1024, 1)} KB` : `${fmt(n / 1024 / 1024, 1)} MB`;

/**
 * Time-axis ticks for a session of any length: a "nice" step (1, 2, 5, 10, 15, 30 or 60 min, or
 * seconds for short sessions) giving at most ~8 labels. Returns [seconds, label].
 */
export function timeTicks(durationSeconds: number): [number, string][] {
  const duration = Math.max(1, durationSeconds);
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];
  const step = steps.find((s) => duration / s <= 8) ?? 3600;
  const ticks: [number, string][] = [];
  for (let t = 0; t <= duration + 0.001; t += step) {
    ticks.push([t, step < 60 ? `${t} s` : `${Math.round(t / 60)} min`]);
  }
  return ticks;
}
