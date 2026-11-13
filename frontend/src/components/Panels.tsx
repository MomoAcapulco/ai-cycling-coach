import { useState } from 'react';
import { api } from '../api';
import { clock, fmt } from '../format';
import type { Sample, Telemetry } from '../types';

const MODE_LABEL: Record<string, string> = { SIMULATOR: 'SIMULADOR', WAHOO: 'RODILLO REAL', REPLAY: 'REPLAY · HISTÓRICO' };

export function Header({ version, data, route }: { version: string; data: Telemetry | null; route: 'panel' | 'rutas' | 'sesiones' | 'ajustes' }) {
  const mode = data?.mode ?? data?.source;
  return (
    <header>
      <div className="brand">
        <span className="logo">↗</span>
        <div><strong>AI CYCLING COACH</strong><small>TRAINING LAB · v{version}</small></div>
      </div>
      <nav className="nav">
        <a href="#/" className={route === 'panel' ? 'active' : ''}>Panel</a>
        <a href="#/rutas" className={route === 'rutas' ? 'active' : ''}>Rutas</a>
        <a href="#/sesiones" className={route === 'sesiones' ? 'active' : ''}>Sesiones</a>
        <a href="#/ajustes" className={route === 'ajustes' ? 'active' : ''}>Ajustes</a>
        <span className={`mode ${mode === 'REPLAY' ? 'replay' : ''}`}>{mode ? MODE_LABEL[mode] ?? mode : 'CONECTANDO'}</span>
      </nav>
    </header>
  );
}

const battery = (pct: number | null | undefined) => (pct == null ? '' : ` · ${pct} %`);

/** Several unknown devices nearby: the adapter waits for the rider's choice in Ajustes (never guesses). */
const mustChoose = (text?: string | null) => !!text && (text.includes('elige uno en Ajustes') || text === 'CHOOSE_IN_SETTINGS');
const CHOOSE = <a href="#/ajustes">elige cuál en Ajustes</a>;

/** Why a device is not streaming, in a few words: the adapter's message without the technical prefix. */
const reason = (text?: string | null) =>
  text ? text.replace(/^(HR BLE|BLE): [A-Za-z]+Error: /, '').replace(/^(HR BLE|BLE): /, '') : '';

export function StatusBar({ data }: { data: Telemetry | null }) {
  return (
    <div className="statuses">
      <span className={data?.connected ? 'ok' : 'off'}>● Telemetría: {mustChoose(data?.error) ? <>varios rodillos cerca, {CHOOSE}</> : data?.status ?? 'Esperando'}</span>
      <span className={data?.heartRateConnected ? 'ok' : 'off'}>● Pulso: {mustChoose(data?.heartRateError) ? <>varias bandas cerca, {CHOOSE}</>
        : data?.heartRateConnected || data?.heartRateStatus === 'DISABLED' ? data?.heartRateStatus
          : <>{data?.heartRateStatus ?? 'Esperando'}{reason(data?.heartRateError) && ` · ${reason(data?.heartRateError)}`}</>}</span>
      <span className={data?.zwiftLeftConnected ? 'ok' : 'off'}>
        ● Mando izq.: {mustChoose(data?.zwiftLeftStatus) ? CHOOSE : data?.zwiftLeftStatus ?? 'Sin datos'}{battery(data?.zwiftLeftBatteryPercent)}
      </span>
      <span className={data?.zwiftRightConnected ? 'ok' : 'off'}>
        ● Mando der.: {mustChoose(data?.zwiftRightStatus) ? CHOOSE : data?.zwiftRightStatus ?? 'Sin datos'}{battery(data?.zwiftRightBatteryPercent)}
      </span>
    </div>
  );
}

export function Metrics({ data, power3s }: { data: Telemetry | null; power3s: number | null }) {
  const road = data?.roadGradePercent ?? null;
  const target = data?.targetGradePercent ?? null;
  const onTrainer = data?.gradeControlMode === 'TRAINER';
  const hasRoad = road != null;
  const grade = hasRoad ? road : target;
  const gradeNote = !hasRoad
    ? (grade == null ? 'Sin orden en esta fase' : 'Pendiente ordenada (registro antiguo)')
    : target == null ? 'Llano: elige una pendiente en el panel'
      : `Pedida ${fmt(target, 1)} %${onTrainer ? ` · rodillo ${fmt(data?.gradeConfirmed ? data?.appliedGradePercent : data?.effectiveGradePercent, 1)} %${data?.gradeConfirmed ? ' ✓' : ''}` : ''}`;
  const speed = data?.rideSpeedKph ?? data?.speedKph;
  const gain = data?.sessionElevationGainM ?? data?.elevationGainM;
  return (
    <section className="metrics">
      <article className="metric emphasis"><span>POTENCIA</span><div><strong>{fmt(data?.powerWatts)}</strong><em>W</em></div><small>Media 3 s: {fmt(power3s)} W{data?.wattsPerKg != null ? ` · ${fmt(data.wattsPerKg, 2)} W/kg` : ''}</small></article>
      <article className="metric"><span>PULSO</span><div><strong>{fmt(data?.heartRateBpm)}</strong><em>ppm</em></div><small>Banda de pulso</small></article>
      <article className="metric"><span>CADENCIA</span><div><strong>{fmt(data?.cadenceRpm)}</strong><em>rpm</em></div><small>Revoluciones/min</small></article>
      <article className="metric"><span>VELOCIDAD</span><div><strong>{fmt(speed, 1)}</strong><em>km/h</em></div><small>{data?.rideSpeedKph != null ? `En la carretera virtual · rodillo ${fmt(data?.speedKph, 1)} km/h` : 'Velocidad del rodillo'}</small></article>
      <article className="metric slope-metric"><span>{hasRoad ? 'PENDIENTE' : 'PENDIENTE ORDENADA'}</span><div><strong>{fmt(grade, 1)}</strong><em>%</em></div><small>{gradeNote}</small></article>
      <article className="metric"><span>DESNIVEL</span><div><strong>{fmt(gain, 0)}</strong><em>m</em></div><small>{data?.altitudeM != null ? `VAM ${fmt(data?.vamMh, 0)} m/h · ${data?.sessionElevationGainM != null ? 'en la sesión' : 'desde que arrancó'}` : 'Sin carretera virtual'}</small></article>
    </section>
  );
}

/**
 * Replay controls. The timeline is dragged locally and the seek is sent once, on release (pointer
 * or keyboard), instead of one request per pixel.
 */
export function ReplayPlayer({ data, duration, firstCommandAt, onError }: {
  data: Telemetry | null; duration: number; firstCommandAt: number | null; onError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState<number | null>(null);
  const position = Math.min(data?.elapsedSeconds ?? 0, duration);
  const run = async (action: string, value?: number) => {
    setBusy(true);
    try { await api.replayControl(action, value); onError(''); }
    catch (e) { onError(`Reproductor: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  const commit = () => {
    if (dragging != null) void run('seek', dragging);
    setDragging(null);
  };
  return (
    <section className="panel replay-panel">
      <div className="panel-heading">
        <h2>Reproductor de sesión</h2>
        <span>{data?.replayPlaying ? 'REPRODUCIENDO' : 'PAUSADO / FINALIZADO'} · {clock(dragging ?? position)} / {clock(duration)}</span>
      </div>
      <input className="timeline" aria-label="Posición de la reproducción" type="range" min={0} max={duration} step={1}
        value={dragging ?? position}
        onChange={(e) => setDragging(Number(e.target.value))}
        onPointerUp={commit} onKeyUp={commit} onBlur={() => dragging != null && commit()} />
      <div className="replay-actions">
        <div>
          <button disabled={busy} onClick={() => void run(data?.replayPlaying ? 'pause' : 'play')}>
            {data?.replayPlaying ? '⏸ Pausar' : '▶ Reproducir'}
          </button>
          <button disabled={busy} onClick={() => void run('restart')}>↺ Reiniciar</button>
          {firstCommandAt != null && (
            <button disabled={busy} onClick={() => void run('seek', firstCommandAt)}>Ir a la primera orden ({clock(firstCommandAt)})</button>
          )}
        </div>
        <label>Velocidad
          <select disabled={busy} value={data?.replaySpeed ?? 1} onChange={(e) => void run('speed', Number(e.target.value))}>
            <option value={0.5}>0,5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option>
          </select>
        </label>
      </div>
    </section>
  );
}

const GEAR_STATUS: Record<string, string> = {
  STARTING: 'Conectando con el rodillo…',
  READY: 'Marcha confirmada por el rodillo',
  WAITING_CONFIRMATION: 'Esperando confirmación del rodillo…',
  UNCONFIRMED: 'El rodillo no confirmó el cambio: se mantiene la última marcha confirmada',
  DISCONNECTED: 'Rodillo desconectado: se restablecerá la marcha al reconectar',
  NO_ZWIFT_CHANNEL: 'Este rodillo no ofrece el canal Zwift: sin control de marchas',
  STOPPED: 'Control de marchas detenido',
};

/**
 * Gears. With native shifting on the trainer the big number is the gear the TRAINER CONFIRMED (never the
 * requested one as if applied). In REPLAY the gears are a visual model only.
 */
export function GearPanel({ data, replay, onError }: { data: Telemetry | null; replay: boolean; onError: (msg: string) => void }) {
  const [busy, setBusy] = useState(false);
  const onTrainer = data?.gearControlMode === 'TRAINER';
  const count = data?.virtualGearCount ?? 24;
  const shown = onTrainer ? data?.trainerGear ?? null : data?.virtualGear ?? 12;
  const requested = data?.requestedGear ?? data?.virtualGear ?? 12;
  const pending = onTrainer && shown != null && requested !== shown;
  const canShift = (replay || onTrainer) && !busy;
  const shift = async (delta: 1 | -1) => {
    setBusy(true);
    try { await api.gear(delta); onError(''); }
    catch (e) { onError(`Marchas: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  return (
    <article className="panel control-panel">
      <div className="panel-heading">
        <h2>Marchas virtuales</h2>
        <span className={onTrainer ? 'live-tag' : ''}>{onTrainer ? 'CONTROLAN EL RODILLO' : 'SOLO VISUAL'}</span>
      </div>
      <div className="gear-display">
        <span>Marcha</span>
        <strong>{shown ?? '—'}<small> / {count}</small></strong>
      </div>
      {pending && <p className="tiny">Pedida: {requested} · esperando al rodillo</p>}
      <div className="gear-buttons">
        <button disabled={!canShift || requested <= 1} onClick={() => void shift(-1)}>− Más fácil</button>
        <button disabled={!canShift || requested >= count} onClick={() => void shift(1)}>+ Más duro</button>
      </div>
      {onTrainer ? (
        <>
          <p className="tiny">{GEAR_STATUS[data?.gearStatus ?? ''] ?? data?.gearStatus}
            {data?.trainerGearRatio ? ` · relación ${fmt(data.trainerGearRatio, 2)}` : ''}</p>
          {data?.gearLastRefusal && <p className="tiny warn">Se rechazó endurecer: sin pedalear (o sin datos del rodillo) la marcha no sube.</p>}
          <p className="tiny">Mandos: «+» derecho endurece, «−» izquierdo suaviza. Al salir, el rodillo vuelve a la marcha 12.</p>
        </>
      ) : (
        <>
          <p className="tiny">Relación relativa: {fmt(data?.virtualGearRelativeRatio, 2)}× (tabla de 24 marchas de Zwift).</p>
          <p className="tiny">{replay ? 'En replay las marchas son solo visuales.' : 'Para que muevan el rodillo, activa el control de marchas en Ajustes (modo rodillo real).'}</p>
        </>
      )}
      <p className="tiny">Último botón: {data?.lastButton ?? 'ninguno'}</p>
    </article>
  );
}

export function SessionStats({ data, points }: { data: Telemetry | null; points: Sample[] }) {
  const maxGrade = points.reduce<number | null>((a, p) => (p.grade == null ? a : Math.max(a ?? p.grade, p.grade)), null);
  return (
    <article className="panel stats">
      <h2>Sesión</h2>
      <div><span>Distancia</span><strong>{fmt(data?.sessionDistanceKm ?? data?.estimatedDistanceKm ?? data?.rideDistanceKm, 2)} km</strong></div>
      <div><span>Desnivel acumulado</span><strong>{fmt(data?.sessionElevationGainM ?? data?.elevationGainM, 0)} m</strong></div>
      <div><span>Trabajo mecánico</span><strong>{fmt(data?.sessionWorkKj ?? data?.mechanicalWorkKj, 1)} kJ</strong></div>
      <div><span>Pendiente máxima</span><strong>{fmt(maxGrade, 1)} %</strong></div>
      <div><span>Fuente</span><strong>{data?.source ?? '—'}</strong></div>
    </article>
  );
}
