import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import type { Telemetry } from '../types';

const MIN = -15;
const MAX = 20;
const STEP = 0.5;
const SEND_AFTER_MS = 300;   // quick presses are added up and sent once, like the gear presses (80 ms there)

const GRADE_STATUS: Record<string, string> = {
  STARTING: 'Conectando con el rodillo…',
  FLAT_START: 'Llano de arranque (0,4 %): elige una pendiente para cambiarla',
  RAMPING: 'Ajustando poco a poco hacia la pendiente efectiva…',
  SET: 'Pendiente aplicada: confirmada por el rodillo',
  UNCONFIRMED: 'El rodillo no confirma la pendiente; se sigue reintentando',
  HOLD_NOT_PEDALLING: 'En pausa: sin pedalear (o sin datos del rodillo) la pendiente no sube',
  DISCONNECTED: 'Rodillo desconectado: al reconectar volverá a subir poco a poco',
  NO_ZWIFT_CHANNEL: 'Este rodillo no ofrece el canal Zwift: sin control de pendiente',
  STOPPED: 'Control detenido: el rodillo quedó en 0,4 %',
};

const pct = (value: number | null | undefined) => (value == null ? '—' : `${fmt(value, 1)} %`);

/**
 * Grade chosen by the rider: the ONLY way it changes. The slider is dragged locally and sent once,
 * on release. Shows asked (target), effective (after difficulty and limits) and the last value sent.
 */
export function GradePanel({ data, onError }: { data: Telemetry | null; onError: (msg: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState<number | null>(null);
  // What the rider has just asked with the buttons, before the telemetry (1 s) shows it: every press adds to
  // THIS value, not to the last telemetry reading (that made quick presses count only once per second).
  const [pending, setPending] = useState<number | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const target = data?.targetGradePercent ?? null;
  const current = pending ?? target ?? 0;
  useEffect(() => {
    if (pending != null && target != null && Math.abs(target - pending) < 0.05) setPending(null);  // caught up
  }, [target, pending]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const onTrainer = data?.gradeControlMode === 'TRAINER';
  const onRoute = !!data?.routeFile && !data?.routeFinished;
  const leaveRoute = async () => {
    setBusy(true);
    try { await api.stopRoute(); onError(''); }
    catch (e) { onError(`Ruta: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };

  const clamp = (value: number) => Math.min(MAX, Math.max(MIN, Math.round(value * 10) / 10));
  const send = async (value: number) => {
    setBusy(true);
    try { await api.grade(clamp(value)); onError(''); }
    catch (e) { setPending(null); onError(`Pendiente: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  /** A +/−0.5 press: shown at once, sent once the presses stop. */
  const press = (delta: number) => {
    const next = clamp(current + delta);
    setPending(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { void send(next); }, SEND_AFTER_MS);
  };
  const commit = () => {
    if (dragging != null) {
      window.clearTimeout(timer.current);   // a slider choice replaces any presses not sent yet
      setPending(clamp(dragging));
      void send(dragging);
    }
    setDragging(null);
  };

  return (
    <article className="panel control-panel">
      <div className="panel-heading">
        <h2>Pendiente</h2>
        <span className={onTrainer ? 'live-tag' : ''}>{onTrainer ? 'CONTROLA EL RODILLO' : 'SIMULADOR · SOLO LA CARRETERA'}</span>
      </div>
      <div className="gear-display">
        <span>Pedida</span>
        <strong>{dragging != null ? fmt(dragging, 1) : pending != null ? fmt(pending, 1) : target == null ? '—' : fmt(target, 1)}<small> %</small></strong>
      </div>
      {onRoute && (
        <div className="notice">
          Rodando la ruta <strong>{data?.routeName}</strong>: {fmt(data?.routeProgressKm, 2)} de {fmt(data?.routeDistanceKm, 1)} km.
          La pendiente la marca la ruta. <button disabled={busy} onClick={() => void leaveRoute()}>Salir de la ruta</button>
        </div>
      )}
      {data?.routeFile && data?.routeFinished && (
        <div className="notice">Ruta «{data?.routeName}» terminada: ahora en llano. <button disabled={busy} onClick={() => void leaveRoute()}>Cerrar ruta</button></div>
      )}
      <input className="timeline" aria-label="Pendiente pedida" type="range" min={MIN} max={MAX} step={STEP}
        disabled={busy || onRoute} value={dragging ?? current}
        onChange={(e) => setDragging(Number(e.target.value))}
        onPointerUp={commit} onKeyUp={commit} onBlur={() => dragging != null && commit()} />
      <div className="grade-buttons">
        <button disabled={onRoute || current <= MIN} onClick={() => press(-STEP)}>−0,5 %</button>
        <button disabled={busy || onRoute} onClick={() => { window.clearTimeout(timer.current); setPending(0); void send(0); }}>Llano 0 %</button>
        <button disabled={onRoute || current >= MAX} onClick={() => press(STEP)}>+0,5 %</button>
      </div>
      <div className={`grade-figures ${onTrainer ? 'three' : ''}`}>
        <div><span>Carretera</span><strong>{pct(data?.roadGradePercent)}</strong></div>
        {onTrainer && <div><span>Rodillo</span><strong>{pct(data?.effectiveGradePercent)}</strong></div>}
        {onTrainer && (
          <div><span>{data?.gradeConfirmed ? 'Aplicada ✓' : 'Enviada · sin confirmar'}</span>
            <strong>{pct(data?.gradeConfirmed ? data?.appliedGradePercent : data?.sentGradePercent)}</strong></div>
        )}
      </div>
      {onTrainer && <p className="tiny">{GRADE_STATUS[data?.gradeStatus ?? ''] ?? data?.gradeStatus}</p>}
      <p className="tiny">
        Como en una carretera de verdad, la pendiente cambia según avanzas: 1 % cada {fmt(data?.gradeTransitionMetersPerPercent, 0)} m
        (parado no cambia). {onTrainer && `El rodillo aplica la dificultad ${data?.gradeDifficultyPercent ?? '—'} % (bajadas ×${data?.gradeDescentFactorPercent ?? '—'} %), entre ${pct(data?.gradeMinPercent)} y ${pct(data?.gradeMaxPercent)}.`} Se cambia en Ajustes → Perfil.
      </p>
      {onTrainer
        ? <p className="tiny">«Aplicada ✓» es la pendiente que el rodillo confirma tener puesta (lo pregunta tras cada cambio).</p>
        : <p className="tiny">En el simulador solo cambia la carretera virtual (velocidad, distancia, desnivel), para probarlo sin rodillo.</p>}
    </article>
  );
}
