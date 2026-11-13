import { useEffect, useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import type { Drivetrain, RiderProfile } from '../types';

type Draft = {
  riderWeightKg: string; bikeWeightKg: string; ftpWatts: string; drivetrain: Drivetrain;
  gradeDifficultyPercent: string; gradeDescentFactorPercent: string; maxGradePercent: string; minGradePercent: string;
  gradeTransitionMetersPerPercent: string;
};

const toDraft = (p: RiderProfile): Draft => ({
  riderWeightKg: String(p.riderWeightKg), bikeWeightKg: String(p.bikeWeightKg),
  ftpWatts: p.ftpWatts == null ? '' : String(p.ftpWatts), drivetrain: p.drivetrain,
  gradeDifficultyPercent: String(p.gradeDifficultyPercent), gradeDescentFactorPercent: String(p.gradeDescentFactorPercent),
  maxGradePercent: String(p.maxGradePercent), minGradePercent: String(p.minGradePercent),
  gradeTransitionMetersPerPercent: String(p.gradeTransitionMetersPerPercent),
});

/** Spanish keyboards type "9,5": accept a comma as the decimal separator. */
const number = (text: string) => Number(text.trim().replace(',', '.'));

/**
 * Rider profile: weights for the physics and speed, FTP for limits and metrics, and the drivetrain.
 * Saving it does not restart anything. Out-of-range values are rejected by the adapter.
 */
export function ProfileSection() {
  const [saved, setSaved] = useState<RiderProfile | null>(null);
  const [isSaved, setIsSaved] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.profile()
      .then((r) => { setSaved(r.profile); setIsSaved(r.saved); setDraft(toDraft(r.profile)); })
      .catch((e) => setError(`No se pudo leer el perfil: ${e instanceof Error ? e.message : e}`));
  }, []);

  if (!draft || !saved) return error ? <div className="alert">{error}</div> : null;

  const set = (changes: Partial<Draft>) => { setDraft({ ...draft, ...changes }); setNotice(''); };
  const rider = number(draft.riderWeightKg);
  const bike = number(draft.bikeWeightKg);
  const ftp = draft.ftpWatts.trim() === '' ? null : number(draft.ftpWatts);
  const difficulty = number(draft.gradeDifficultyPercent);
  const descent = number(draft.gradeDescentFactorPercent);
  const maxGrade = number(draft.maxGradePercent);
  const minGrade = number(draft.minGradePercent);
  const transition = number(draft.gradeTransitionMetersPerPercent);
  const gradeOk = Number.isFinite(transition) && Number.isInteger(difficulty) && Number.isInteger(descent) && Number.isFinite(maxGrade) && Number.isFinite(minGrade);
  const numbersOk = Number.isFinite(rider) && Number.isFinite(bike) && (ftp === null || Number.isInteger(ftp)) && gradeOk;
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(saved));

  const save = async () => {
    setBusy(true);
    try {
      const result = await api.saveProfile({
        riderWeightKg: rider, bikeWeightKg: bike, ftpWatts: ftp, drivetrain: draft.drivetrain,
        gradeDifficultyPercent: difficulty, gradeDescentFactorPercent: descent, maxGradePercent: maxGrade, minGradePercent: minGrade,
        gradeTransitionMetersPerPercent: transition,
      });
      setSaved(result.profile);
      setIsSaved(true);
      setDraft(toDraft(result.profile));
      setError('');
      setNotice('Perfil guardado.');
    } catch (e) {
      setError(`No se guardó el perfil: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-heading"><h2>Perfil del ciclista</h2><span>{isSaved ? 'GUARDADO' : 'VALORES POR DEFECTO · SIN GUARDAR'}</span></div>
      {error && <div className="alert">{error}</div>}
      {notice && <div className="notice">{notice}</div>}
      <div className="profile-grid">
        <label className="field-block">Peso del ciclista
          <span><input inputMode="decimal" value={draft.riderWeightKg} onChange={(e) => set({ riderWeightKg: e.target.value })} /> kg</span>
        </label>
        <label className="field-block">Peso de la bici
          <span><input inputMode="decimal" value={draft.bikeWeightKg} onChange={(e) => set({ bikeWeightKg: e.target.value })} /> kg</span>
        </label>
        <label className="field-block">FTP (opcional)
          <span><input inputMode="numeric" placeholder="no lo sé" value={draft.ftpWatts} onChange={(e) => set({ ftpWatts: e.target.value })} /> W</span>
        </label>
        <label className="field-block">Transmisión
          <select value={draft.drivetrain} onChange={(e) => set({ drivetrain: e.target.value as Drivetrain })}>
            <option value="ZWIFT_COG">Zwift Cog (marchas virtuales)</option>
            <option value="CASSETTE">Cassette (marchas de la bici)</option>
          </select>
        </label>
      </div>
      <h3 className="subheading">Pendiente en el rodillo</h3>
      <div className="profile-grid">
        <label className="field-block">Dificultad (0–100)
          <span><input inputMode="numeric" value={draft.gradeDifficultyPercent} onChange={(e) => set({ gradeDifficultyPercent: e.target.value })} /> %</span>
        </label>
        <label className="field-block">Factor en bajadas (0–100)
          <span><input inputMode="numeric" value={draft.gradeDescentFactorPercent} onChange={(e) => set({ gradeDescentFactorPercent: e.target.value })} /> %</span>
        </label>
        <label className="field-block">Máxima efectiva (0,5–20)
          <span><input inputMode="decimal" value={draft.maxGradePercent} onChange={(e) => set({ maxGradePercent: e.target.value })} /> %</span>
        </label>
        <label className="field-block">Mínima efectiva (−10–0)
          <span><input inputMode="decimal" value={draft.minGradePercent} onChange={(e) => set({ minGradePercent: e.target.value })} /> %</span>
        </label>
        <label className="field-block">Transición: metros por cada 1 % (5–100)
          <span><input inputMode="decimal" value={draft.gradeTransitionMetersPerPercent} onChange={(e) => set({ gradeTransitionMetersPerPercent: e.target.value })} /> m</span>
        </label>
      </div>
      <p className="tiny">
        Como la «dificultad del rodillo» de Zwift: con 50 %, una rampa del 8 % se siente como un 4 %. En bajada se aplica
        además el factor de bajadas. La pendiente efectiva nunca sale de los límites. La transición hace que la pendiente
        cambie según avanzas, como en una carretera: con 20 m, pasar del 0 al 5 % lleva unos 100 m. Se aplica al momento, sin reiniciar.
      </p>
      <p className="tiny">
        Masa total: {numbersOk ? fmt(rider + bike, 1) : '—'} kg. Los pesos se usan para la simulación y la velocidad;
        el FTP, para los límites de seguridad y métricas como IF y TSS. Sin FTP esas métricas se muestran como «sin FTP».
      </p>
      <div className="admin-actions">
        <button className="primary" disabled={busy || !dirty || !numbersOk} onClick={() => void save()}>{busy ? 'Guardando…' : 'Guardar perfil'}</button>
        <button disabled={busy || !dirty} onClick={() => { setDraft(toDraft(saved)); setNotice(''); }}>Descartar</button>
        {!numbersOk && <span className="tiny">Revisa los números (el FTP, la dificultad y el factor de bajadas, enteros).</span>}
      </div>
    </section>
  );
}
