import { useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import type { Telemetry } from '../types';

const MIN = -15;
const MAX = 20;
const STEP = 0.5;

const GRADE_STATUS: Record<string, string> = {
  STARTING: 'Conectando con el rodillo…',
  FLAT_START: 'Llano de arranque (0,4 %): elige una pendiente para cambiarla',
  RAMPING: 'Ajustando poco a poco hacia la pendiente efectiva…',
  SET: 'Pendiente enviada al rodillo',
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
  const target = data?.targetGradePercent ?? null;
  const current = target ?? 0;
  const onTrainer = data?.gradeControlMode === 'TRAINER';

  const send = async (value: number) => {
    const clamped = Math.min(MAX, Math.max(MIN, Math.round(value * 10) / 10));
    setBusy(true);
    try { await api.grade(clamped); onError(''); }
    catch (e) { onError(`Pendiente: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  const commit = () => {
    if (dragging != null) void send(dragging);
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
        <strong>{dragging != null ? fmt(dragging, 1) : target == null ? '—' : fmt(target, 1)}<small> %</small></strong>
      </div>
      <input className="timeline" aria-label="Pendiente pedida" type="range" min={MIN} max={MAX} step={STEP}
        disabled={busy} value={dragging ?? current}
        onChange={(e) => setDragging(Number(e.target.value))}
        onPointerUp={commit} onKeyUp={commit} onBlur={() => dragging != null && commit()} />
      <div className="grade-buttons">
        <button disabled={busy || current <= MIN} onClick={() => void send(current - STEP)}>−0,5 %</button>
        <button disabled={busy} onClick={() => void send(0)}>Llano 0 %</button>
        <button disabled={busy || current >= MAX} onClick={() => void send(current + STEP)}>+0,5 %</button>
      </div>
      <div className={`grade-figures ${onTrainer ? 'three' : ''}`}>
        <div><span>Carretera</span><strong>{pct(data?.roadGradePercent)}</strong></div>
        {onTrainer && <div><span>Rodillo</span><strong>{pct(data?.effectiveGradePercent)}</strong></div>}
        {onTrainer && <div><span>Enviada</span><strong>{pct(data?.sentGradePercent)}</strong></div>}
      </div>
      {onTrainer && <p className="tiny">{GRADE_STATUS[data?.gradeStatus ?? ''] ?? data?.gradeStatus}</p>}
      <p className="tiny">
        Como en una carretera de verdad, la pendiente cambia según avanzas: 1 % cada {fmt(data?.gradeTransitionMetersPerPercent, 0)} m
        (parado no cambia). {onTrainer && `El rodillo aplica la dificultad ${data?.gradeDifficultyPercent ?? '—'} % (bajadas ×${data?.gradeDescentFactorPercent ?? '—'} %), entre ${pct(data?.gradeMinPercent)} y ${pct(data?.gradeMaxPercent)}.`} Se cambia en Ajustes → Perfil.
      </p>
      {onTrainer
        ? <p className="tiny">«Enviada» es lo último que se mandó al rodillo; el rodillo aún no confirma la pendiente.</p>
        : <p className="tiny">En el simulador solo cambia la carretera virtual (velocidad, distancia, desnivel), para probarlo sin rodillo.</p>}
    </article>
  );
}
