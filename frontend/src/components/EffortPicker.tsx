import { useState } from 'react';
import { api } from '../api';
import type { SessionFeedback } from '../types';
import { toast } from '../toast';

/** Perceived effort 1–10 (Borg CR10, like Strava and TrainingPeaks). */
export const RPE_LABELS: Record<number, string> = {
  1: 'muy, muy suave', 2: 'muy suave', 3: 'suave', 4: 'moderado', 5: 'algo duro', 6: 'duro', 7: 'muy duro',
  8: 'muy, muy duro', 9: 'casi máximo', 10: 'máximo',
};
export const rpeColor = (rpe: number) => `hsl(${Math.round(140 - (rpe - 1) * 15)}, 60%, 55%)`;

/** «¿Cómo te has sentido?»: 1–10 and a note, saved in the session (and seen by the history). */
export function EffortPicker({ session, initial, compact = false, onSaved }: {
  session: string; initial?: SessionFeedback | null; compact?: boolean; onSaved?: (f: SessionFeedback) => void;
}) {
  const [rpe, setRpe] = useState<number | null>(initial?.rpe ?? null);
  const [note, setNote] = useState(initial?.note ?? '');
  const [saved, setSaved] = useState<SessionFeedback | null>(initial ?? null);
  const [busy, setBusy] = useState(false);
  const dirty = rpe !== (saved?.rpe ?? null) || (note.trim() || null) !== (saved?.note ?? null);
  const save = async (value = rpe) => {
    setBusy(true);
    try { const f = await api.sessionFeedback(session, { rpe: value, note }); setSaved(f); onSaved?.(f); }
    catch (e) { toast.error(`No se guardó el esfuerzo: ${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  };
  return (
    <div className={`effort ${compact ? 'compact' : ''}`}>
      <span className="effort-title">¿Cómo te has sentido?{rpe ? <> <strong style={{ color: rpeColor(rpe) }}>{rpe}/10 · {RPE_LABELS[rpe]}</strong></> : ' (esfuerzo de 1 a 10)'}</span>
      <div className="effort-scale">
        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
          <button key={n} title={RPE_LABELS[n]} className={rpe === n ? 'selected' : ''} disabled={busy}
            style={rpe === n ? { background: rpeColor(n), borderColor: rpeColor(n), color: '#0b1a1c' } : { borderColor: rpeColor(n) }}
            onClick={() => setRpe(rpe === n ? null : n)}>{n}</button>
        ))}
      </div>
      <div className="effort-note">
        <input maxLength={500} placeholder="Nota (opcional): piernas, sueño, molestias…" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className={dirty ? 'primary' : ''} disabled={busy || !dirty} onClick={() => void save()}>{saved && !dirty ? 'Guardado ✓' : 'Guardar'}</button>
      </div>
    </div>
  );
}
