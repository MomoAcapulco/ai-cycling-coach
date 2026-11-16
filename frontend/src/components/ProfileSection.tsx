import { useEffect, useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import type { BikeType, Drivetrain, RiderProfile } from '../types';
import { Help } from './Help';

type Draft = {
  riderWeightKg: string; bikeWeightKg: string; ftpWatts: string; drivetrain: Drivetrain;
  gradeDifficultyPercent: string; gradeDescentFactorPercent: string; maxGradePercent: string; minGradePercent: string;
  gradeTransitionMetersPerPercent: string;
  bikeType: BikeType;
  restingHeartRate: string; maxHeartRate: string; thresholdHeartRate: string;
};

const toDraft = (p: RiderProfile): Draft => ({
  riderWeightKg: String(p.riderWeightKg), bikeWeightKg: String(p.bikeWeightKg),
  ftpWatts: p.ftpWatts == null ? '' : String(p.ftpWatts), drivetrain: p.drivetrain,
  gradeDifficultyPercent: String(p.gradeDifficultyPercent), gradeDescentFactorPercent: String(p.gradeDescentFactorPercent),
  maxGradePercent: String(p.maxGradePercent), minGradePercent: String(p.minGradePercent),
  gradeTransitionMetersPerPercent: String(p.gradeTransitionMetersPerPercent),
  bikeType: p.bikeType ?? 'ROAD',
  restingHeartRate: p.restingHeartRate == null ? '' : String(p.restingHeartRate),
  maxHeartRate: p.maxHeartRate == null ? '' : String(p.maxHeartRate),
  thresholdHeartRate: p.thresholdHeartRate == null ? '' : String(p.thresholdHeartRate),
});
const optionalWhole = (text: string) => (text.trim() === '' ? null : Number(text.trim()));

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
  const hrRest = optionalWhole(draft.restingHeartRate), hrMax = optionalWhole(draft.maxHeartRate), hrThreshold = optionalWhole(draft.thresholdHeartRate);
  const hrOk = [hrRest, hrMax, hrThreshold].every((v) => v === null || Number.isInteger(v));
  const gradeOk = hrOk && Number.isFinite(transition) && Number.isInteger(difficulty) && Number.isInteger(descent) && Number.isFinite(maxGrade) && Number.isFinite(minGrade);
  const numbersOk = Number.isFinite(rider) && Number.isFinite(bike) && (ftp === null || Number.isInteger(ftp)) && gradeOk;
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(saved));

  const save = async () => {
    setBusy(true);
    try {
      const result = await api.saveProfile({
        riderWeightKg: rider, bikeWeightKg: bike, ftpWatts: ftp, drivetrain: draft.drivetrain,
        gradeDifficultyPercent: difficulty, gradeDescentFactorPercent: descent, maxGradePercent: maxGrade, minGradePercent: minGrade,
        gradeTransitionMetersPerPercent: transition, bikeType: draft.bikeType,
        restingHeartRate: hrRest, maxHeartRate: hrMax, thresholdHeartRate: hrThreshold,
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
        <label className="field-block">Tipo de bici
          <select value={draft.bikeType} onChange={(e) => set({ bikeType: e.target.value as BikeType })}>
            <option value="ROAD">Carretera</option>
            <option value="MTB">BTT (montaña)</option>
          </select>
        </label>
        <label className="field-block">Transmisión
          <select value={draft.drivetrain} onChange={(e) => set({ drivetrain: e.target.value as Drivetrain })}>
            <option value="ZWIFT_COG">Zwift Cog (marchas virtuales)</option>
            <option value="CASSETTE">Cassette (marchas de la bici)</option>
          </select>
        </label>
      </div>
      <Help label="Tipo de bici y transmisión">
      <p>
        Tipo de bici: cambia la física de la carretera virtual y la rodadura que se manda al rodillo. En BTT vas más erguido
        y con tacos sobre tierra: más lento en llano (con 200 W y 90 kg en total, unos 27 km/h en vez de 32) y el llano se nota más duro en
        el rodillo. En subida casi no cambia. Los valores de BTT son una estimación, aún sin validar con el rodillo.
      </p>
      </Help>
      <h3 className="subheading">Pulso (para la carga de entrenamiento)</h3>
      <div className="profile-grid">
        <label className="field-block">En reposo (opcional)
          <span><input inputMode="numeric" placeholder="60" value={draft.restingHeartRate} onChange={(e) => set({ restingHeartRate: e.target.value })} /> ppm</span>
        </label>
        <label className="field-block">Máximo (opcional)
          <span><input inputMode="numeric" placeholder="del historial" value={draft.maxHeartRate} onChange={(e) => set({ maxHeartRate: e.target.value })} /> ppm</span>
        </label>
        <label className="field-block">Umbral (opcional)
          <span><input inputMode="numeric" placeholder="90 % del máximo" value={draft.thresholdHeartRate} onChange={(e) => set({ thresholdHeartRate: e.target.value })} /> ppm</span>
        </label>
      </div>
      <Help label="¿Para qué sirve el pulso?">
      <p>Con ellos se calcula la carga de lo que haces sin potencia (bici en la calle, carrera, fuerza). Si los dejas
        vacíos se estiman: el máximo con tu historial, el umbral como el 90 % del máximo y 60 en reposo. El reposo, mídelo al despertar.</p>
      </Help>
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
      <Help label="¿Qué es cada valor?">
      <p>
        Como la «dificultad del rodillo» de Zwift: con 50 %, una rampa del 8 % se siente como un 4 %. En bajada se aplica
        además el factor de bajadas. La pendiente efectiva nunca sale de los límites. La transición hace que la pendiente
        cambie según avanzas, como en una carretera: con 20 m, pasar del 0 al 5 % lleva unos 100 m. Se aplica al momento, sin reiniciar.
      </p>
      <p>Los pesos se usan para la simulación y la velocidad; el FTP, para los límites de seguridad y métricas como IF y TSS.
        Sin FTP se usa el estimado con tu historial.</p>
      </Help>
      <p className="tiny">Masa total: {numbersOk ? fmt(rider + bike, 1) : '—'} kg.</p>
      <div className="admin-actions">
        <button className="primary" disabled={busy || !dirty || !numbersOk} onClick={() => void save()}>{busy ? 'Guardando…' : 'Guardar perfil'}</button>
        <button disabled={busy || !dirty} onClick={() => { setDraft(toDraft(saved)); setNotice(''); }}>Descartar</button>
        {!numbersOk && <span className="tiny">Revisa los números (el FTP, la dificultad y el factor de bajadas, enteros).</span>}
      </div>
    </section>
  );
}
