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
export function timeTicks(durationSeconds: number, maxTicks = 8): [number, string][] {
  const duration = Math.max(1, durationSeconds);
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];
  const step = steps.find((s) => duration / s <= maxTicks) ?? 21600;
  const label = (t: number) => (step < 60 ? `${t} s` : step < 3600 ? `${Math.round(t / 60)} min` : `${Math.round(t / 3600)} h`);
  const ticks: [number, string][] = [];
  for (let t = 0; t <= duration + 0.001; t += step) ticks.push([t, label(t)]);
  // A tick right at the end (12 h of a 12 h 04 min ride) would sit on top of the one before it.
  const last = ticks[ticks.length - 1];
  if (ticks.length > 2 && duration - last[0] < step * 0.4) ticks.pop();
  return ticks;
}
