import { useEffect, useState } from 'react';
import { api } from '../api';
import type { DeviceRole, DevicesState, RememberedDevice } from '../types';
import { Help } from './Help';
import { toast } from '../toast';

/** A Bluetooth id is long: the end is enough to tell them apart; the whole one on hover. */
const shortId = (id: string) => (id.length > 14 ? `…${id.slice(-8)}` : id);

const ROLES: DeviceRole[] = ['trainer', 'heart_rate', 'zwift_left', 'zwift_right'];
const ROLE_LABEL: Record<DeviceRole, string> = {
  trainer: 'Rodillo', heart_rate: 'Pulsómetro', zwift_left: 'Mando izquierdo', zwift_right: 'Mando derecho',
};
const REFRESH_MS = 5000;

const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' }) : '—';
const signal = (rssi: number | null) => (rssi == null ? '' : rssi > -60 ? 'señal fuerte' : rssi > -75 ? 'señal media' : 'señal débil');

/**
 * Every device used for each role (not only the last one). The adapter picks the preferred one if it is around,
 * else the most recently used one; with several UNKNOWN devices and no known one it does not guess and lists them
 * here to choose. Refreshes every few seconds so new candidates show up.
 */
export function DevicesSection({ initial }: { initial: DevicesState | null }) {
  const [devices, setDevices] = useState<DevicesState | null>(initial);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setDevices(initial); }, [initial]);
  useEffect(() => {
    const timer = window.setInterval(() => { api.devices().then(setDevices).catch(() => undefined); }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const run = async (action: () => Promise<DevicesState>) => {
    setBusy(true);
    try { setDevices(await action()); }
    catch (e) { toast.error(`Dispositivos: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  const use = (role: DeviceRole, d: { address: string }) => void run(() => api.useDevice(role, d.address));
  const forget = (role: DeviceRole, d: RememberedDevice) => {
    if (!window.confirm(`¿Olvidar «${d.name ?? d.address}» como ${ROLE_LABEL[role].toLowerCase()}?`)) return;
    void run(() => api.forgetDevice(role, d.address));
  };

  return (
    <section className="panel">
      <div className="panel-heading"><h2>Dispositivos <Help title="Cómo funcionan los dispositivos">
      <p>
        Se encuentran por su tipo (lo que anuncian por Bluetooth), de cualquier marca, y se recuerdan todos los que has
        usado. Al conectar se usa el preferido si está
        cerca; si no, el último que usaste. Si hay varios desconocidos y ninguno conocido, no se elige al azar: aparecen
        aquí para que elijas. El pulsómetro y los mandos cambian al momento; el rodillo, en la siguiente conexión.
      </p>
      </Help></h2><span>AUTODESCUBRIMIENTO</span></div>
      {ROLES.map((role) => {
        const known = devices?.known?.[role] ?? [];
        const pending = devices?.pending?.[role] ?? [];
        const filter = devices?.envFilters?.[role];
        return (
          <div className="device-role" key={role}>
            <h3 className="subheading">{ROLE_LABEL[role]}</h3>
            {filter?.id && <p className="tiny warn">Fijado en .env por identificador: solo se usa ese dispositivo.</p>}
            {pending.length > 0 && (
              <div className="notice">
                Hay {pending.length} posibles cerca y ninguno conocido. ¿Cuál es el tuyo?
                <table className="devices"><tbody>
                  {pending.map((c) => (
                    <tr key={c.address}>
                      <td>{c.name ?? 'sin nombre'}</td><td className="tiny">{signal(c.rssi)}</td>
                      <td className="mono" title={c.address}>{shortId(c.address)}</td>
                      <td><button className="primary" disabled={busy} onClick={() => use(role, c)}>Este es el mío</button></td>
                    </tr>
                  ))}
                </tbody></table>
              </div>
            )}
            {known.length === 0 && pending.length === 0 && <p className="tiny muted">Aún no se ha encontrado ninguno.</p>}
            {known.length > 0 && (
              <table className="devices">
                <thead><tr><th>Dispositivo</th><th>Modelo</th><th>Último uso</th><th>Identificador</th><th /></tr></thead>
                <tbody>
                  {known.map((d, i) => (
                    <tr key={d.address}>
                      <td>{d.name ?? '—'} {d.preferred ? <span className="live-tag">PREFERIDO</span> : i === 0 ? <span className="tiny">(se usa primero)</span> : null}</td>
                      <td>{d.zwiftModel ?? d.kind}</td>
                      <td>{when(d.lastUsedAtUtc)}</td>
                      <td className="mono" title={d.address}>{shortId(d.address)}</td>
                      <td className="device-actions">
                        {!d.preferred && <button disabled={busy} onClick={() => use(role, d)}>Usar este</button>}
                        <button disabled={busy} onClick={() => forget(role, d)}>Olvidar</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </section>
  );
}
