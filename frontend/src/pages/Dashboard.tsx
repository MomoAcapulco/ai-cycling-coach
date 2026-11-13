import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { average, clock } from '../format';
import type { ActiveRoute, Sample, Session, Telemetry } from '../types';
import { ElevationProfile, GradeProfile, RouteProfile, TraceChart } from '../components/Charts';
import { GradePanel } from '../components/GradePanel';
import { GearPanel, Metrics, ReplayPlayer, SessionStats, StatusBar } from '../components/Panels';
import { SessionBar } from '../components/SessionBar';

const SUBTITLE: Record<string, string> = {
  REPLAY: 'Reproducción de una sesión grabada · ninguna orden al rodillo',
  WAHOO: 'Lectura en directo del rodillo',
  SIMULATOR: 'Datos simulados para probar la aplicación sin rodillo',
};

export function Dashboard({ data, error, history }: { data: Telemetry | null; error: string; history: Sample[] }) {
  const replay = data?.source === 'REPLAY';
  const [session, setSession] = useState<Session | null>(null);
  const [actionError, setActionError] = useState('');
  const [fullView, setFullView] = useState(false);
  const [route, setRoute] = useState<ActiveRoute | null>(null);
  const routeFile = data?.routeFile ?? null;

  // The profile of the route being ridden is loaded once per route; the position comes with the telemetry.
  useEffect(() => {
    if (!routeFile) { setRoute(null); return; }
    let alive = true;
    api.route().then((r) => { if (alive) setRoute(r); }).catch(() => undefined);
    return () => { alive = false; };
  }, [routeFile]);
  const replayKey = replay ? `${data?.replayFile}:${data?.replayDurationSeconds}` : '';

  // The full recorded session is loaded once per replay file.
  useEffect(() => {
    if (!replay) { setSession(null); return; }
    let alive = true;
    api.replaySession()
      .then((s) => { if (alive) setSession(s); })
      .catch((e) => { if (alive) setActionError(`Sesión grabada: ${e instanceof Error ? e.message : e}`); });
    return () => { alive = false; };
  }, [replay, replayKey]);

  const points = replay ? session?.samples ?? [] : history;
  // The big timer is the SESSION time: from «Iniciar sesión», running while you stop pedalling, without the
  // time spent in «Pausar». Before a session starts there is nothing to time. The live charts use the same clock
  // during a session (hooks.useTelemetry), the adapter time otherwise, and the replay position in REPLAY.
  const sessionState = data?.sessionState ?? 'UNAVAILABLE';
  const inSession = sessionState === 'RUNNING' || sessionState === 'PAUSED';
  const lastPoint = history[history.length - 1]?.t ?? 0;
  const seconds = replay ? data?.elapsedSeconds ?? 0
    : inSession ? Math.round(data?.sessionElapsedSeconds ?? 0)
      : sessionState === 'IDLE' && history.length && lastPoint < (data?.elapsedSeconds ?? 0) - 5 ? lastPoint  // finished session on screen
        : data?.elapsedSeconds ?? 0;
  const timerSeconds = replay ? seconds : inSession ? data?.sessionElapsedSeconds ?? 0 : null;
  const duration = replay
    ? session?.durationSeconds ?? data?.replayDurationSeconds ?? 1
    : Math.max(600, points[points.length - 1]?.t ?? 0);
  // Mean power over the last 3 s of TIME (not of samples), so gaps do not stretch the window.
  const power3s = useMemo(
    () => average(points.filter((p) => p.t <= seconds && p.t > seconds - 3 && p.power != null).map((p) => p.power as number)),
    [points, seconds],
  );
  const firstCommandAt = points.find((p) => p.grade != null)?.t ?? null;
  const shownError = error || actionError;
  const mode = data?.mode ?? data?.source ?? '';

  return (
    <>
      <div className="heading">
        <div>
          <p className="eyebrow">PANEL DE ENTRENAMIENTO</p>
          <h1>Tu sesión, en detalle</h1>
          <p className="muted">{SUBTITLE[mode] ?? 'Conectando con el adaptador…'}</p>
        </div>
        <div className="timer">
          <small>{replay ? 'POSICIÓN DEL REPLAY' : 'TIEMPO DE SESIÓN'}</small>
          <strong>{timerSeconds == null ? '--:--' : clock(timerSeconds)}</strong>
          {replay && <small>de {clock(duration)}</small>}
          {!replay && sessionState === 'PAUSED' && <small>EN PAUSA</small>}
          {!replay && !inSession && <small>Pulsa «Iniciar sesión»</small>}
        </div>
      </div>
      {shownError && <div className="alert">{shownError}</div>}
      <StatusBar data={data} />
      {!replay && <SessionBar data={data} onError={setActionError} />}
      <Metrics data={data} power3s={power3s} />
      {replay && <ReplayPlayer data={data} duration={duration} firstCommandAt={firstCommandAt} onError={setActionError} />}
      {route?.active && (
        <section className="panel">
          <RouteProfile profile={route.profile} progressKm={data?.routeProgressKm ?? route.progressKm}
            title={`Ruta: ${route.name}${data?.routeFinished ? ' · TERMINADA' : ''}`} />
        </section>
      )}
      {!route?.active && points.some((p) => p.distance != null) && (
        <section className="panel"><ElevationProfile points={points} current={seconds} fullView={replay && fullView} /></section>
      )}
      <section className="panel"><GradeProfile points={points} current={seconds} duration={duration} kind={session?.gradeKind} /></section>
      {replay && (
        <div className="display-mode">
          <span>Visualización de gráficas</span>
          <div>
            <button className={!fullView ? 'selected' : ''} onClick={() => setFullView(false)}>Durante la sesión</button>
            <button className={fullView ? 'selected' : ''} onClick={() => setFullView(true)}>Análisis completo</button>
          </div>
        </div>
      )}
      <div className="workspace">
        <section className="left">
          {([['power', 'Potencia', '#6ce8af', 'W'], ['heart', 'Frecuencia cardíaca', '#fb8c83', 'ppm'], ['cadence', 'Cadencia', '#aab5ff', 'rpm'], ['speed', 'Velocidad', '#f6c180', 'km/h']] as const).map(
            ([field, title, color, unit]) => (
              <article className="panel" key={field}>
                <div className="panel-heading">
                  <h2>{title}</h2>
                  <span>{replay ? (fullView ? 'ANÁLISIS COMPLETO' : 'PROGRESO REPLAY') : 'HISTÓRICO EN DIRECTO'}</span>
                </div>
                <TraceChart points={points} field={field} color={color} unit={unit} current={seconds} duration={duration} fullView={replay && fullView} />
              </article>
            ),
          )}
        </section>
        <section className="right">
          <GearPanel data={data} replay={replay} onError={setActionError} />
          {(data?.gradeControlMode === 'TRAINER' || data?.gradeControlMode === 'SIMULATED') && <GradePanel data={data} onError={setActionError} />}
          <SessionStats data={data} points={points} />
        </section>
      </div>
      <footer>{data?.gearControlMode === 'TRAINER' ? 'Las marchas y la pendiente controlan el rodillo (protocolo Zwift nativo); la pendiente solo cambia cuando tú la eliges.' : 'Las marchas son solo visuales: no cambian la resistencia del rodillo.'} Los datos se quedan en este ordenador.</footer>
    </>
  );
}
