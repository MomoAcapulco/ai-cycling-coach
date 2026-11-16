import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { average, clock } from '../format';
import type { ActiveRoute, Sample, Session, Telemetry } from '../types';
import { ElevationProfile, GradeProfile, RouteProfile, TraceChart } from '../components/Charts';
import { GradePanel } from '../components/GradePanel';
import { RampTestPanel } from '../components/RampTestPanel';
import { WorkoutPanel } from '../components/WorkoutPanel';
import { FtpNotice } from '../components/FtpNotice';
import { GearPanel, Metrics, ReplayPlayer, SessionStats, StatusBar } from '../components/Panels';
import { SessionBar } from '../components/SessionBar';
import { toast } from '../toast';

const SUBTITLE: Record<string, string> = {
  REPLAY: 'Reproducción de una sesión grabada · ninguna orden al rodillo',
  WAHOO: 'Lectura en directo del rodillo',
  SIMULATOR: 'Datos simulados para probar la aplicación sin rodillo',
};

export function Dashboard({ data, error, history }: { data: Telemetry | null; error: string; history: Sample[] }) {
  const replay = data?.source === 'REPLAY';
  const [session, setSession] = useState<Session | null>(null);
  /** Button errors go to the floating messages (toast.ts); '' means «it worked» and shows nothing. */
  const setActionError = (msg: string) => { if (msg) toast.error(msg); };
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
  // A replay of a session ridden on a route draws that route with the position of the moment.
  const [replayRoute, setReplayRoute] = useState<{ name: string; profile: { d: number; e: number; g: number }[] } | null>(null);
  const replayRouteFile = replay ? session?.routes?.[0]?.file ?? null : null;
  useEffect(() => {
    if (!replayRouteFile) { setReplayRoute(null); return; }
    let alive = true;
    api.routePreview(replayRouteFile).then((r) => { if (alive) setReplayRoute({ name: r.name, profile: r.profile }); })
      .catch(() => { if (alive) setReplayRoute(null); });   // the route was deleted: the replay goes on without it
    return () => { alive = false; };
  }, [replayRouteFile]);
  // The big timer is the SESSION time: from «Iniciar sesión», running while you stop pedalling, without the
  // time spent in «Pausar». Before a session starts there is nothing to time and nothing to show: the numbers and
  // charts are the session's (hooks.useTelemetry) or the replay's. After «Terminar» the last session stays.
  const sessionState = data?.sessionState ?? 'UNAVAILABLE';
  const inSession = sessionState === 'RUNNING' || sessionState === 'PAUSED';
  const idle = !replay && !inSession;
  const lastPoint = history[history.length - 1]?.t ?? 0;
  const seconds = replay ? data?.elapsedSeconds ?? 0 : inSession ? Math.round(data?.sessionElapsedSeconds ?? 0) : lastPoint;
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
  // Only charts that say something: a flat ride has no profile worth half a screen, and no heart rate no chart.
  const altitudes = points.map((p) => p.altitude).filter((a): a is number => a != null);
  const hilly = altitudes.length > 1 && Math.max(...altitudes) - Math.min(...altitudes) >= 2;
  const gradeChanges = points.some((p) => p.grade != null && Math.abs(p.grade) >= 0.1);
  const hasHeart = points.some((p) => p.heart != null);
  const shownError = error;   // the adapter not answering: a state of the page, so it stays in it
  const mode = data?.mode ?? data?.source ?? '';

  return (
    <>
      <div className="heading">
        <div>
          <p className="eyebrow">PANEL DE ENTRENAMIENTO</p>
          <h1>{replay ? 'Replay de una sesión' : sessionState === 'PAUSED' ? 'Sesión en pausa' : inSession ? 'Sesión en curso' : 'Listo para rodar'}</h1>
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
      {idle && !data?.workoutType && sessionState === 'IDLE' && <FtpNotice />}
      <Metrics data={data} power3s={power3s} idle={idle} />
      {replay && <ReplayPlayer data={data} duration={duration} firstCommandAt={firstCommandAt} onError={setActionError} />}
      {data?.workoutType === 'STRUCTURED' && <WorkoutPanel data={data} power3s={power3s} onError={setActionError} />}
      {replay && replayRoute && (
        <section className="panel dash-panel">
          <RouteProfile profile={replayRoute.profile} progressKm={data?.routeProgressKm ?? null} title={`Ruta: ${replayRoute.name}`} />
        </section>
      )}
      {route?.active && (
        <section className="panel dash-panel">
          <RouteProfile profile={route.profile} progressKm={data?.routeProgressKm ?? route.progressKm}
            title={`Ruta: ${route.name}${data?.routeFinished ? ' · TERMINADA' : ''}`} />
        </section>
      )}
      {/* the route's own profile (above) already draws the altitude and where you are: no second, emptier one */}
      {!route?.active && !replayRoute && hilly && (
        <section className="panel dash-panel"><ElevationProfile points={points} current={seconds} fullView={replay && fullView} /></section>
      )}
      {(gradeChanges || (replay && session?.gradeKind === 'ORDERED_NOT_MEASURED' && firstCommandAt != null)) && (
        <section className="panel dash-panel"><GradeProfile points={points} current={seconds} duration={duration} kind={session?.gradeKind} /></section>
      )}
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
          {!replay && history.length === 0 && (
            <article className="panel empty-state">
              <h2>Sin sesión</h2>
              <p className="muted">Las gráficas empiezan al pulsar «Iniciar sesión». Para ver una sesión ya hecha, ábrela desde Sesiones → «Ver en replay».</p>
            </article>
          )}
          {(replay || history.length > 0) && ([['power', 'Potencia', '#6ce8af', 'W'], ['heart', 'Frecuencia cardíaca', '#fb8c83', 'ppm'], ['cadence', 'Cadencia', '#aab5ff', 'rpm'], ['speed', 'Velocidad', '#f6c180', 'km/h']] as const)
            // a replay shows only what was recorded (a GPX from Strava may bring no power); live, the heart only with a strap
            .filter(([field]) => (replay ? points.some((p) => p[field] != null) : field !== 'heart' || hasHeart)).map(
            ([field, title, color, unit]) => (
              <article className="panel" key={field}>
                <div className="panel-heading">
                  <h2>{title}</h2>
                  <span>{replay ? (fullView ? 'ANÁLISIS COMPLETO' : 'PROGRESO REPLAY') : inSession ? 'EN DIRECTO' : 'ÚLTIMA SESIÓN'}</span>
                </div>
                <TraceChart points={points} field={field} color={color} unit={unit} current={seconds} duration={duration} fullView={replay && fullView} />
              </article>
            ),
          )}
        </section>
        <section className="right">
          <GearPanel data={data} replay={replay} onError={setActionError} />
          {(data?.gradeControlMode === 'TRAINER' || data?.gradeControlMode === 'SIMULATED') && <GradePanel data={data} onError={setActionError} />}
          {!replay && data?.workoutType !== 'STRUCTURED' && <RampTestPanel data={data} power3s={power3s} onError={setActionError} />}
          <SessionStats data={data} points={points} />
        </section>
      </div>
      <footer>Los datos se quedan en este ordenador.</footer>
    </>
  );
}
