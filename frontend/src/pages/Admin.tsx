import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { AdminState, DevicesState, Settings } from '../types';
import { exitReplay, LIVE_LABEL, lastLiveMode } from '../liveMode';
import { DevicesSection } from '../components/DevicesSection';
import { ProfileSection } from '../components/ProfileSection';
import { Help } from '../components/Help';
import { toast } from '../toast';



const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Ajustes is split in pages (#/ajustes/<id>); Privacidad comes with sharing data (docs/PENDIENTES-sin-rodillo.md 10d). */
const TABS = [
  { id: 'perfil', label: 'Perfil', title: 'Tu perfil de ciclista' },
  { id: 'rodillo', label: 'Rodillo y dispositivos', title: 'El rodillo, los sensores y los mandos' },
] as const;
type Tab = typeof TABS[number]['id'];
const readTab = (): Tab => {
  const sub = window.location.hash.replace(/^#\/?ajustes\/?/, '');
  return (TABS.find((t) => t.id === sub)?.id) ?? 'perfil';
};

export function Admin() {
  const [admin, setAdmin] = useState<AdminState | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [devices, setDevices] = useState<DevicesState | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>(readTab);
  useEffect(() => {
    const onChange = () => setTab(readTab());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

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
          <h1>{TABS.find((t) => t.id === tab)?.title}</h1>
          <p className="muted">Los cambios se aplican al momento, sin reiniciar.</p>
        </div>
      </div>
      <nav className="tabs" aria-label="Apartados de Ajustes">
        {TABS.map((t) => <a key={t.id} href={`#/ajustes/${t.id}`} className={t.id === tab ? 'active' : ''}
          aria-current={t.id === tab ? 'page' : undefined}>{t.label}</a>)}
      </nav>

      {error && <div className="alert">{error}</div>}
      {locked && (
        <div className="alert">
          El control físico experimental está activado en .env (CONTROL_TEST_ENABLED). Mientras lo esté, la configuración queda fijada: rodillo real, grabación de 600 s.
        </div>
      )}

      {tab === 'perfil' && <ProfileSection />}
      {tab === 'rodillo' && <>

      {/* The app reads the trainer. A replay is opened from Sessions or Routes; the simulator is for development
          only (TRAINER_MODE=SIMULATOR in .env): neither is chosen here, but both can be left from here. */}
      {current.mode !== 'WAHOO' && (
        <div className="notice">
          {inReplay ? <>Estás viendo un replay ({current.replayFile ?? '—'}).</> : <>Estás en el simulador (modo de desarrollo, del fichero .env).</>}{' '}
          <button disabled={busy || locked} onClick={() => {
            setBusy(true);
            (inReplay ? exitReplay() : api.saveSettings({ mode: 'WAHOO' })).then(() => load())
              .catch((e) => toast.error(`No se pudo cambiar: ${message(e)}`)).finally(() => setBusy(false));
          }}>{inReplay ? `Salir del replay (volver a ${LIVE_LABEL[lastLiveMode()]})` : 'Usar el rodillo real'}</button>
        </div>
      )}


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

      <section className="panel">
        <div className="panel-heading"><h2>Control de marchas del rodillo <Help title="Cómo funciona el control de marchas"><p>
          24 marchas de Zwift, empieza en la 12. Cada cambio lo confirma el rodillo; sin pedalear no se endurece;
          al salir vuelve a la 12. La pendiente no cambia. Usa los pesos del perfil del ciclista.
        </p></Help></h2><span>ZWIFT COG · CON EL RODILLO</span></div>
        <label className="switch">
          <input type="checkbox" checked={draft.gearControlEnabled} disabled={locked}
            onChange={(e) => set({ gearControlEnabled: e.target.checked })} />
          <span>Las marchas (mandos y botones del panel) cambian la resistencia del rodillo</span>
        </label>
        {draft.gearControlEnabled && !draft.zwiftEnabled && <p className="tiny warn">Activa también los mandos Zwift para cambiar con ellos.</p>}
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Captura Bluetooth en bruto</h2><span>DIAGNÓSTICO · CON EL RODILLO</span></div>
        <label className="switch">
          <input type="checkbox" checked={draft.recordEnabled} disabled={locked} onChange={(e) => set({ recordEnabled: e.target.checked })} />
          <span>Guardar también todos los mensajes Bluetooth de cada sesión (para analizar problemas)</span>
        </label>
        <p className="tiny">Las sesiones se inician y terminan desde el Panel; el CSV de la sesión se guarda siempre.</p>
      </section>

      <div className="admin-actions">
        <button className="primary" disabled={busy || !dirty || locked} onClick={() => void apply()}>
          {busy ? 'Aplicando…' : 'Aplicar'}
        </button>
        <button disabled={busy || !dirty} onClick={() => setDraft(current)}>Descartar cambios</button>
        <button disabled={busy || admin.source !== 'saved' || locked} onClick={() => void reset()}
          title="Los valores del fichero .env de la instalación">Restaurar valores por defecto</button>
      </div>

      <DevicesSection initial={devices} />
      </>}
    </div>
  );
}
