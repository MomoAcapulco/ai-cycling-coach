import { useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import type { GeneratedRoute, RouteSummary } from '../types';
import { RouteProfile } from './Charts';
import { Help } from './Help';

type Custom = { distanceKm: number; gainM: number; climbs: number; avgGrade: number; maxGrade: number; kicks: number; descentGrade: number };
const START: Custom = { distanceKm: 40, gainM: 800, climbs: 4, avgGrade: 6, maxGrade: 12, kicks: 3, descentGrade: 6 };
const FIELDS: [keyof Custom, string, string, number][] = [
  ['distanceKm', 'Distancia', 'km', 1], ['gainM', 'Desnivel', 'm', 50], ['climbs', 'Subidas', '', 1],
  ['avgGrade', 'Pendiente media', '%', 0.5], ['maxGrade', 'Pendiente máxima', '%', 0.5], ['kicks', 'Repechos', '', 1],
  ['descentGrade', 'Bajadas', '%', 0.5],
];

/**
 * Make a route: custom (distance, gain, climbs…) or like one of your races but shorter. Preview first (with a seed);
 * «Otra variante» changes the seed; «Guardar» stores that same route as a GPX in the list below.
 */
export function RouteGenerator({ races, onSaved }: { races: RouteSummary[]; onSaved: () => void }) {
  const [mode, setMode] = useState<'custom' | 'like'>('custom');
  const [custom, setCustom] = useState<Custom>(START);
  const [race, setRace] = useState(races[0]?.file ?? '');
  const [likeKm, setLikeKm] = useState(40);
  const [preview, setPreview] = useState<GeneratedRoute | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const raceFile = race || races[0]?.file || '';
  const body = (seed?: number, save = false) => (mode === 'custom'
    ? { mode, ...custom, seed, save } : { mode, file: raceFile, distanceKm: likeKm, seed, save });
  const run = async (seed?: number, save = false) => {
    setBusy(true);
    try {
      const r = await api.generateRoute(body(seed, save));
      setError('');
      if (save) { setPreview(null); onSaved(); } else setPreview(r);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setPreview(null); }
    finally { setBusy(false); }
  };
  const chosen = races.find((r) => r.file === raceFile);

  return (
    <section className="panel route-generator">
      <div className="panel-heading"><h2>Generar una ruta</h2><span>A MEDIDA O COMO TU CARRERA</span></div>
      <div className="display-mode">
        <div>
          <button className={mode === 'custom' ? 'selected' : ''} onClick={() => { setMode('custom'); setPreview(null); }}>A medida</button>
          <button className={mode === 'like' ? 'selected' : ''} disabled={!races.length} onClick={() => { setMode('like'); setPreview(null); }}>Como mi carrera</button>
        </div>
      </div>
      {mode === 'custom' ? (
        <div className="profile-grid">
          {FIELDS.map(([key, label, unit, step]) => (
            <label key={key} className="field-block">{label}
              <span><input type="number" step={step} value={custom[key]}
                onChange={(e) => { setCustom({ ...custom, [key]: Number(e.target.value) }); setPreview(null); }} /> {unit}</span>
            </label>
          ))}
        </div>
      ) : (
        <div className="profile-grid">
          <label className="field-block">Carrera
            <select value={raceFile} onChange={(e) => { setRace(e.target.value); setPreview(null); }}>
              {races.map((r) => <option key={r.file} value={r.file}>{r.name}</option>)}
            </select>
          </label>
          <label className="field-block">Distancia
            <span><input type="number" step={1} value={likeKm} onChange={(e) => { setLikeKm(Number(e.target.value)); setPreview(null); }} /> km</span>
          </label>
          {chosen && <p className="tiny">{chosen.name}: {fmt(chosen.distanceKm, 0)} km y {fmt(chosen.elevationGainM, 0)} m
            ({fmt((chosen.elevationGainM ?? 0) / (chosen.distanceKm || 1), 0)} m/km). En {likeKm} km saldrían unos {fmt((chosen.elevationGainM ?? 0) / (chosen.distanceKm || 1) * likeKm, 0)} m.</p>}
        </div>
      )}
      <Help>
        {mode === 'custom'
          ? <p>Cada subida va por tramos de unos 300 m cuya pendiente cambia poco a poco alrededor de la media, con una rampa a la
            pendiente máxima. Los repechos son golpes cortos (150–400 m) entre las subidas. Entre medias, llanos con ondulaciones
            suaves. El desnivel se ajusta al que pides, medido igual que en esta página.</p>
          : <p>Usa las subidas de verdad de la carrera (con su pendiente metro a metro) y la bajada que va después de cada una, en el
            mismo orden, eligiendo las que mantienen los metros de desnivel por km. La subida más dura siempre entra. El resto, llanos.</p>}
        <p>El recorrido es una línea inventada: en el rodillo solo cuentan la distancia y el desnivel. Cada variante tiene un número
          (semilla): la misma semilla da la misma ruta.</p>
      </Help>
      {error && <div className="alert">{error}</div>}
      <div className="admin-actions">
        <button className="primary" disabled={busy || (mode === 'like' && !raceFile)} onClick={() => void run()}>{busy ? 'Generando…' : preview ? 'Otra variante' : 'Vista previa'}</button>
        {preview && <button className="primary" disabled={busy} onClick={() => void run(preview.seed, true)}>Guardar esta ruta</button>}
      </div>
      {preview && (
        <>
          <div className="session-grid">
            <div><span>Distancia</span><strong>{fmt(preview.distanceKm, 1)} km</strong></div>
            <div><span>Desnivel +</span><strong>{fmt(preview.elevationGainM, 0)} m</strong></div>
            <div><span>Pendiente máx.</span><strong>{fmt(preview.maxGradePercent, 1)} %</strong></div>
            <div><span>Variante</span><strong>n.º {preview.seed}</strong></div>
          </div>
          <RouteProfile profile={preview.profile} progressKm={null} title="Vista previa" />
        </>
      )}
    </section>
  );
}
