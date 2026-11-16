import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { AdminState, DevicesState, Mode, Settings } from '../types';
import { exitReplay, LIVE_LABEL, lastLiveMode } from '../liveMode';
import { DevicesSection } from '../components/DevicesSection';
import { ProfileSection } from '../components/ProfileSection';
import { Help } from '../components/Help';
import { toast } from '../toast';

const MODES: { mode: Mode; title: string; text: string }[] = [
  { mode: 'WAHOO', title: 'Rodillo real', text: 'Lee el rodillo por Bluetooth. Sin órdenes de resistencia.' },
  { mode: 'SIMULATOR', title: 'Simulador', text: 'Datos inventados para probar la aplicación.' },
];


const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function Admin() {
  const [admin, setAdmin] = useState<AdminState | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [devices, setDevices] = useState<DevicesState | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, d] = await Promise.all([api.adminState(), api.devices()]);
      setAdmin(a);
      setDraft(a.settings);
      setDevices(d);
      setError('');
    } catch (e) {
      setError(`No se pudieron leer los ajustes: ${message(e)}`);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (!admin || !draft) {
    return <div className="admin">{error ? <div className="alert">{error}</div> : <p className="muted">Cargando ajustes…</p>}</div>;
  }

  const current = admin.settings;
  const dirty = JSON.stringify(draft) !== JSON.stringify(current);
  const set = (changes: Partial<Settings>) => setDraft({ ...draft, ...changes });
  const inReplay = current.mode === 'REPLAY';
  const locked = admin.controlTestEnabled;

  const apply = async () => {
    setBusy(true);
    try {
      const changes = Object.fromEntries(
        Object.entries(draft).filter(([k, v]) => current[k as keyof Settings] !== v),
      ) as Partial<Settings>;
      const result = await api.saveSettings(changes);
      setAdmin(result);
      setDraft(result.settings);
      toast.ok('Ajustes aplicados. El panel ya muestra la nueva fuente de datos.');
    } catch (e) {
      toast.error(`No se aplicaron los ajustes: ${message(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm('¿Restaurar los valores por defecto (fichero .env)? Se borran la fuente de datos y los sensores guardados desde esta página; tu perfil no cambia.')) return;
    setBusy(true);
    try {
      const result = await api.resetSettings();
      setAdmin(result);
      setDraft(result.settings);
      toast.ok('Valores por defecto restaurados.');
    } catch (e) {
      toast.error(`No se pudieron restaurar los valores por defecto: ${message(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin">
      <div className="heading">
        <div>
          <p className="eyebrow">AJUSTES</p>
          <h1>Tu perfil, la fuente de datos y los dispositivos</h1>
          <p className="muted">Los cambios se aplican al momento, sin reiniciar.</p>
        </div>
      </div>

      {error && <div className="alert">{error}</div>}
      {locked && (
        <div className="alert">
          El control físico experimental está activado en .env (CONTROL_TEST_ENABLED). Mientras lo esté, la configuración queda fijada: rodillo real, grabación de 600 s.
        </div>
      )}

      <ProfileSection />

      <section className="panel">
        <div className="panel-heading"><h2>Fuente de datos</h2><span>ACTUAL: {inReplay ? 'REPLAY' : MODES.find((m) => m.mode === current.mode)?.title.toUpperCase() ?? current.mode}</span></div>
        {inReplay && (
          <div className="notice">Estás viendo un replay ({current.replayFile ?? '—'}).{' '}
            <button disabled={busy || locked} onClick={() => { setBusy(true); exitReplay().then(() => load()).catch((e) => toast.error(`No se pudo salir del replay: ${message(e)}`)).finally(() => setBusy(false)); }}>
              Salir del replay (volver a {LIVE_LABEL[lastLiveMode()]})</button>
          </div>
        )}
        <div className="mode-cards" role="radiogroup" aria-label="Fuente de datos">
          {MODES.map(({ mode, title, text }) => (
            <button key={mode} role="radio" aria-checked={draft.mode === mode} disabled={locked}
              className={`mode-card ${draft.mode === mode ? 'selected' : ''}`} onClick={() => set({ mode })}>
              <strong>{title}</strong><span>{text}</span>
            </button>
          ))}
        </div>
        <p className="tiny">Para ver una sesión o una ruta en replay: <a href="#/sesiones">Sesiones</a> → «Ver en replay», o <a href="#/rutas">Rutas</a>.</p>
      </section>


      <section className="panel">
        <div className="panel-heading"><h2>Sensores</h2><span>BLUETOOTH</span></div>
        <label className="switch">
          <input type="checkbox" checked={draft.hrEnabled} disabled={locked} onChange={(e) => set({ hrEnabled: e.target.checked })} />
          <span>Pulsómetro{draft.mode === 'REPLAY' ? ' (en replay se usa el pulso grabado)' : ''}</span>
        </label>
        <label className="switch">
          <input type="checkbox" checked={draft.zwiftEnabled} disabled={locked} onChange={(e) => set({ zwiftEnabled: e.target.checked })} />
          <span>Mandos Zwift (se buscan solos)</span>
        </label>
      </section>

      {draft.mode === 'WAHOO' && (
        <section className="panel">
          <div className="panel-heading"><h2>Control de marchas del rodillo <Help title="Cómo funciona el control de marchas"><p>
            24 marchas de Zwift, empieza en la 12. Cada cambio lo confirma el rodillo; sin pedalear no se endurece;
            al salir vuelve a la 12. La pendiente no cambia. Usa los pesos del perfil del ciclista.
          </p></Help></h2><span>ZWIFT COG · SOLO RODILLO REAL</span></div>
          <label className="switch">
            <input type="checkbox" checked={draft.gearControlEnabled} disabled={locked}
              onChange={(e) => set({ gearControlEnabled: e.target.checked })} />
            <span>Las marchas (mandos y botones del panel) cambian la resistencia del rodillo</span>
          </label>
          {draft.gearControlEnabled && !draft.zwiftEnabled && <p className="tiny warn">Activa también los mandos Zwift para cambiar con ellos.</p>}
        </section>
      )}

      {draft.mode === 'WAHOO' && (
        <section className="panel">
          <div className="panel-heading"><h2>Captura Bluetooth en bruto</h2><span>DIAGNÓSTICO · SOLO RODILLO REAL</span></div>
          <label className="switch">
            <input type="checkbox" checked={draft.recordEnabled} disabled={locked} onChange={(e) => set({ recordEnabled: e.target.checked })} />
            <span>Guardar también todos los mensajes Bluetooth de cada sesión (para analizar problemas)</span>
          </label>
          <p className="tiny">Las sesiones se inician y terminan desde el Panel; el CSV de la sesión se guarda siempre.</p>
        </section>
      )}

      <div className="admin-actions">
        <button className="primary" disabled={busy || !dirty || locked} onClick={() => void apply()}>
          {busy ? 'Aplicando…' : 'Aplicar'}
        </button>
        <button disabled={busy || !dirty} onClick={() => setDraft(current)}>Descartar cambios</button>
        <button disabled={busy || admin.source !== 'saved' || locked} onClick={() => void reset()}
          title="Los valores del fichero .env de la instalación">Restaurar valores por defecto</button>
      </div>

      <DevicesSection initial={devices} />
    </div>
  );
}
