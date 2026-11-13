import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import { RouteProfile } from '../components/Charts';
import type { ActiveRoute, RouteSummary, Telemetry } from '../types';

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
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
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
      setNotice(`Ruta «${saved.name}» guardada: ${fmt(saved.distanceKm, 1)} km y ${fmt(saved.elevationGainM, 0)} m de desnivel.`);
      await load();
    } catch (e) {
      setError(`No se pudo subir «${file.name}»: ${message(e)}`);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };
  const preview = async (r: RouteSummary) => {
    if (previews[r.file]) { setPreviews(({ [r.file]: _, ...rest }) => rest); return; }
    try { const p = await api.routePreview(r.file); setPreviews((all) => ({ ...all, [r.file]: p.profile })); }
    catch (e) { setError(`No se pudo leer el perfil: ${message(e)}`); }
  };
  const ride = async (r: RouteSummary) => {
    setBusy(true);
    try { await api.startRoute(r.file); window.location.hash = '#/'; }
    catch (e) { setError(`No se pudo empezar la ruta: ${message(e)}`); }
    finally { setBusy(false); }
  };
  const leave = async () => {
    setBusy(true);
    try { await api.stopRoute(); await load(); }
    catch (e) { setError(`No se pudo salir de la ruta: ${message(e)}`); }
    finally { setBusy(false); }
  };

  const current = listing?.current ?? data?.routeFile ?? null;
  return (
    <div className="admin">
      <div className="heading">
        <div>
          <p className="eyebrow">RUTAS</p>
          <h1>Rueda un recorrido real</h1>
          <p className="muted">Sube el GPX de una carrera o de una subida. La pendiente seguirá su perfil según avanzas,
            con la misma transición suave de siempre. Los GPX se guardan en tu carpeta de datos ({listing?.folder ?? '—'}),
            fuera del repositorio.</p>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}
      {notice && <div className="notice">{notice}</div>}
      {listing && !listing.available && (
        <div className="notice">Para rodar una ruta usa el modo Simulador o el rodillo real con el control de marchas activado (Ajustes).</div>
      )}
      <div className="admin-actions">
        <input ref={fileInput} type="file" accept=".gpx,application/gpx+xml" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
        <button className="primary" disabled={busy} onClick={() => fileInput.current?.click()}>Subir GPX</button>
        {current && <button disabled={busy} onClick={() => void leave()}>Salir de la ruta actual</button>}
      </div>
      {listing && listing.routes.length === 0 && <p className="muted">Todavía no hay rutas. Sube un GPX (con altitud).</p>}
      {listing?.routes.map((r) => {
        const active = profiles[r.file];
        return (
          <article className="panel session-card" key={r.file}>
            <div className="panel-heading">
              <h2>{r.name}</h2>
              <span>{r.file === current ? 'RODANDO AHORA' : r.file}</span>
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
                  : previews[r.file] && <RouteProfile profile={previews[r.file]} progressKm={null} compact />}
                {!!r.clippedSteps && <p className="tiny warn">El GPX tenía {r.clippedSteps} tramos de 10 m imposibles (fuera de −15 … +20 %): se han recortado.</p>}
                <div className="admin-actions">
                  <button className="primary" disabled={busy || !listing.available || r.file === current} onClick={() => void ride(r)}>
                    {r.file === current ? 'Rodando' : 'Rodar esta ruta'}
                  </button>
                  {r.file !== current && <button disabled={busy} onClick={() => void preview(r)}>{previews[r.file] ? 'Ocultar perfil' : 'Ver perfil'}</button>}
                </div>
              </>
            ) : <p className="tiny warn">No se puede usar: {r.error}</p>}
          </article>
        );
      })}
    </div>
  );
}
