import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import { RouteProfile } from '../components/Charts';
import type { ActiveRoute, RouteSummary, Telemetry } from '../types';
import { Help } from '../components/Help';
import { RouteGenerator } from '../components/RouteGenerator';
import { RPE_LABELS, rpeColor } from '../components/EffortPicker';
import { toast } from '../toast';

type Listing = { routes: RouteSummary[]; folder: string; current: string | null; available: boolean };

/**
 * GPX routes: upload, list with their profile, and choose one to ride. Choosing a route IS choosing the grade:
 * while it is ridden, the grade follows its profile as you advance (with the usual gradual transition).
 */
export function Routes({ data }: { data: Telemetry | null }) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [profiles, setProfiles] = useState<Record<string, ActiveRoute>>({});
  const [previews, setPreviews] = useState<Record<string, { d: number; e: number; g: number }[]>>({});
  const [error, setError] = useState('');
  /** Actions fail where the user is: a floating message (toast.ts), not at the top of a long page. */
  const fail = (_file: string, text: string) => toast.error(text);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<{ file: string; name: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const load = async () => {
    try { setListing(await api.routes()); setError(''); }
    catch (e) { setError(`No se pudieron leer las rutas: ${message(e)}`); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    if (!data?.routeFile) return;
    api.route().then((r) => { if (r.active) setProfiles((p) => ({ ...p, [r.file]: r })); }).catch(() => undefined);
  }, [data?.routeFile]);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const saved = await api.uploadRoute(file);
      toast.ok(`Ruta «${saved.name}» guardada: ${fmt(saved.distanceKm, 1)} km y ${fmt(saved.elevationGainM, 0)} m de desnivel.`);
      await load();
    } catch (e) {
      toast.error(`No se pudo subir «${file.name}»: ${message(e)}`);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };
  const preview = async (r: RouteSummary) => {
    if (previews[r.file]) { setPreviews(({ [r.file]: _, ...rest }) => rest); return; }
    try { const p = await api.routePreview(r.file); setPreviews((all) => ({ ...all, [r.file]: p.profile })); }
    catch (e) { fail(r.file, `No se pudo leer el perfil: ${message(e)}`); }
  };
  const ride = async (r: RouteSummary) => {
    setBusy(true);
    try { await api.startRoute(r.file); window.location.hash = '#/'; }
    catch (e) { fail(r.file, `No se pudo empezar la ruta: ${message(e)}`); }
    finally { setBusy(false); }
  };
  /** Replay: of the GPX itself when it is a recorded ride («gpx»), or of your newest session on it («session»). */
  const replayRoute = async (r: RouteSummary, what: 'gpx' | 'session') => {
    if (what === 'session' && !r.replayRide?.csv) {
      fail(r.file, `Datos insuficientes para el replay de «${r.name}»: ${r.lastRide ? `${r.lastRide.why} en tu última sesión` : 'todavía no la has rodado'}`
        + `${r.recorded ? '' : ', y el GPX es una ruta planificada (sin los tiempos de cada punto)'}.`);
      return;
    }
    setBusy(true);
    try {
      const file = what === 'gpx' ? (await api.routeReplay(r.file)).replayFile : r.replayRide?.csv as string;
      await api.saveSettings({ mode: 'REPLAY', replayFile: file });
      window.location.hash = '#/';
    } catch (e) { fail(r.file, `No se pudo abrir el replay: ${message(e)}`); }
    finally { setBusy(false); }
  };
  const remove = async (r: RouteSummary) => {
    if (!window.confirm(`¿Borrar «${r.name}»? Se mueve a la papelera de la carpeta de rutas (.papelera); se puede recuperar a mano.`)) return;
    setBusy(true);
    try { await api.deleteRoute(r.file); toast.ok(`«${r.name}» movida a la papelera.`); await load(); }
    catch (e) { fail(r.file, `No se pudo borrar: ${message(e)}`); }
    finally { setBusy(false); }
  };
  const rename = async () => {
    if (!editing) return;
    setBusy(true);
    try { await api.renameRoute(editing.file, editing.name); setEditing(null); await load(); }
    catch (e) { fail(editing.file, `No se pudo cambiar el nombre: ${message(e)}`); }
    finally { setBusy(false); }
  };
  const leave = async () => {
    setBusy(true);
    try { await api.stopRoute(); await load(); }
    catch (e) { toast.error(`No se pudo salir de la ruta: ${message(e)}`); }
    finally { setBusy(false); }
  };

  const current = listing?.current ?? data?.routeFile ?? null;
  return (
    <div className="admin">
      <div className="heading">
        <div>
          <p className="eyebrow">RUTAS</p>
          <h1>Rueda un recorrido real <Help title="Cómo funcionan las rutas">
        <p>La pendiente cambia con la misma transición suave de siempre. Las bajadas de más del −5 % se notan en el rodillo como tu
          límite de bajada (Ajustes → Perfil): el rodillo no puede empujarte cuesta abajo. Sí cuentan para la velocidad y la distancia.</p>
        <p>Los GPX se guardan en tu carpeta de datos, fuera del repositorio: {listing?.folder ?? '—'}</p>
      </Help></h1>
          <p className="muted">Sube el GPX de una carrera o de una subida, o genera una: la pendiente seguirá su perfil según avanzas.</p>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}
      {listing && !listing.available && (
        <div className="notice">Para rodar una ruta usa el modo Simulador o el rodillo real con el control de marchas activado (Ajustes).</div>
      )}
      <div className="admin-actions">
        <input ref={fileInput} type="file" accept=".gpx,application/gpx+xml" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
        <button className="primary" disabled={busy} onClick={() => fileInput.current?.click()}>Subir GPX</button>
        {current && <button disabled={busy} onClick={() => void leave()}>Salir de la ruta actual</button>}
      </div>
      {listing && <RouteGenerator races={listing.routes.filter((r) => r.valid && !r.generated)}
        onSaved={() => { toast.ok('Ruta generada guardada: está la primera de la lista.'); void load(); }} />}
      {listing && listing.routes.length === 0 && <p className="muted">Todavía no hay rutas. Sube un GPX (con altitud).</p>}
      {listing?.routes.map((r) => {
        const active = profiles[r.file];
        return (
          <article className="panel session-card" key={r.file}>
            <div className="panel-heading">
              {editing?.file === r.file ? (
                <div className="rename">
                  <input autoFocus maxLength={80} value={editing.name} placeholder={r.gpxName}
                    onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                    onKeyDown={(e) => { if (e.key === 'Enter') void rename(); if (e.key === 'Escape') setEditing(null); }} />
                  <button className="primary" disabled={busy} onClick={() => void rename()}>Guardar</button>
                  <button disabled={busy} onClick={() => setEditing(null)}>Cancelar</button>
                </div>
              ) : (
                <h2>{r.name} <button className="link-button" title={r.gpxName && r.gpxName !== r.name ? `En el GPX: ${r.gpxName}` : 'Cambiar el nombre'}
                  onClick={() => setEditing({ file: r.file, name: r.name })}>✎ cambiar nombre</button></h2>
              )}
              <span className={r.file === current ? 'live-tag' : ''}>{r.file === current ? 'RODANDO AHORA' : r.generated ? 'GENERADA' : ''}</span>
            </div>
            {r.valid ? (
              <>
                <div className="session-grid">
                  <div><span>Distancia</span><strong>{fmt(r.distanceKm, 1)} km</strong></div>
                  <div><span>Desnivel +</span><strong>{fmt(r.elevationGainM, 0)} m</strong></div>
                  <div><span>Desnivel −</span><strong>{fmt(r.elevationLossM, 0)} m</strong></div>
                  <div><span>Pendiente máx.</span><strong>{fmt(r.maxGradePercent, 1)} %</strong></div>
                </div>
                {active?.active && r.file === current
                  ? <RouteProfile profile={active.profile} progressKm={data?.routeProgressKm ?? active.progressKm} compact />
                  : previews[r.file]
                    ? <RouteProfile profile={previews[r.file]} progressKm={null} />
                    : r.thumb && <RouteProfile profile={r.thumb} progressKm={null} compact />}
                {r.lastRide && (
                  <p className="tiny">Rodada {r.rides === 1 ? 'una vez' : `${r.rides} veces`} · la última el{' '}
                    {r.lastRide.date ? new Date(r.lastRide.date).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' }) : '—'} ({fmt(r.lastRide.km, 1)} km)
                    {r.lastRide.rpe ? <> · esfuerzo <strong style={{ color: rpeColor(r.lastRide.rpe) }}>{r.lastRide.rpe}/10</strong> ({RPE_LABELS[r.lastRide.rpe]})</> : ' · sin esfuerzo anotado (en Sesiones)'}</p>
                )}
                {!!r.clippedSteps && <p className="tiny warn">El GPX tiene {r.clippedSteps} tramos de 5 m con más de ±30 %, casi seguro errores de altitud del GPX: se han recortado a ±30 %.</p>}
                <div className="admin-actions">
                  <button className="primary" disabled={busy || !listing.available || r.file === current} onClick={() => void ride(r)}>
                    {r.file === current ? 'Rodando' : 'Rodar esta ruta'}
                  </button>
                  {r.file !== current && <button disabled={busy} onClick={() => void preview(r)}>{previews[r.file] ? 'Perfil pequeño' : 'Perfil grande'}</button>}
                  {r.recorded && <button disabled={busy} title="Tu recorrido grabado en este GPX: tu velocidad de cada momento (y pulso, cadencia o potencia si los trae)"
                    onClick={() => void replayRoute(r, 'gpx')}>Replay de tu recorrido</button>}
                  {(r.replayRide || !r.recorded) && <button disabled={busy}
                    title={r.replayRide ? `Tu sesión del ${r.replayRide.date ? new Date(r.replayRide.date).toLocaleDateString('es-ES') : '—'} en esta ruta` : 'Necesita una sesión rodada en esta ruta'}
                    onClick={() => void replayRoute(r, 'session')}>{r.recorded ? 'Replay de tu última sesión' : 'Ver en replay'}</button>}
                  <button className="danger" disabled={busy || r.file === current} onClick={() => void remove(r)}>Borrar</button>
                </div>
              </>
            ) : <p className="tiny warn">No se puede usar: {r.error}</p>}
          </article>
        );
      })}
    </div>
  );
}
