import { useEffect, useState } from 'react';
import { api } from '../api';
import { clock, fmt } from '../format';
import type { Telemetry, WorkoutLibrary } from '../types';
import { Help } from '../components/Help';
import { WorkoutBlocks, ZoneLegend } from '../components/WorkoutBlocks';

/**
 * The workout library: blocks with a power target (% of your FTP), ridden without ERG — you reach each target with
 * the gears. Starting one starts a session (if none is running) and goes to the Panel.
 */
export function Workouts({ data }: { data: Telemetry | null }) {
  const [library, setLibrary] = useState<WorkoutLibrary | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

  useEffect(() => {
    api.workoutLibrary().then(setLibrary).catch((e) => setError(`No se pudo leer la biblioteca: ${message(e)}`));
  }, []);

  const start = async (id: string) => {
    setBusy(true);
    try { await api.startWorkout(id); window.location.hash = '#/'; }
    catch (e) { setError(`No se pudo empezar: ${message(e)}`); }
    finally { setBusy(false); }
  };

  const running = !!data?.workoutRunning;
  const replay = data?.source === 'REPLAY';
  const onRoute = !!data?.routeFile && !data?.routeFinished;
  const ftp = library?.ftpW ?? null;
  const blocked = running ? 'Ya hay un entrenamiento en marcha (Panel).' : replay ? 'En modo replay no se puede entrenar: cambia a rodillo real o simulador en Ajustes.'
    : onRoute ? 'Sal de la ruta primero: los entrenamientos se ruedan en llano.' : !ftp ? 'Hace falta tu FTP.' : '';

  return (
    <div className="admin">
      <div className="heading">
        <div>
          <p className="eyebrow">ENTRENAMIENTOS</p>
          <h1>Entrenamientos estructurados</h1>
          <p className="muted">
            {ftp ? <>Objetivos calculados con tu FTP de <strong>{ftp} W</strong>{library?.ftpSource === 'history' ? ' (estimado con tu historial)' : ''}.</>
              : library ? <>Sin FTP no hay objetivos: haz el <a href="#/">test de FTP</a> en el Panel o ponlo en <a href="#/ajustes">Ajustes</a>.</> : 'Cargando…'}
          </p>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}
      {blocked && library && <div className="notice">{blocked}</div>}
      <Help>
        <p>Sin ERG: la aplicación te enseña el objetivo de vatios de cada bloque y tú lo alcanzas con las marchas y la cadencia.
          Al empezar se inicia una sesión (si no había una) y vas al Panel. «Pausar» la sesión pausa también el entrenamiento.</p>
        <p>Al terminar cada bloque se puntúa: <strong>cumplimiento</strong> (tu potencia media frente al objetivo medio) y
          <strong> en rango</strong> (el tiempo a ±10 % del objetivo). Todo queda en la sesión, con su FIT.</p>
        <p>IF y TSS son los del entrenamiento hecho tal cual.</p>
      </Help>
      <ZoneLegend />
      {library?.workouts.map((w) => (
        <article className="panel session-card" key={w.id}>
          <div className="panel-heading">
            <h2>{w.name}</h2>
            <span>{clock(w.seconds)} · IF {fmt(w.intensityFactor, 2)} · TSS {w.tss}</span>
          </div>
          <p className="muted">{w.goal}</p>
          <WorkoutBlocks blocks={w.blocks} />
          <div className="admin-actions">
            <button className="primary" disabled={busy || !!blocked} onClick={() => void start(w.id)}>Empezar</button>
            <span className="tiny">{clock(w.workSeconds)} de trabajo
              {ftp && ` · bloques de trabajo a ${[...new Set(w.blocks.filter((b) => b.kind === 'WORK').map((b) => b.startW))].join(' / ')} W`}</span>
          </div>
        </article>
      ))}
    </div>
  );
}
