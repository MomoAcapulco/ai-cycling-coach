import { useEffect, useMemo, useRef, useState } from 'react';
import { api, type GoalInput, type RaceRef } from '../api';
import { clock, fmt } from '../format';
import type { ActivityType, CalendarMonth, DayActivity, Goal, GoalKind, GoalStage } from '../types';
import { Help } from '../components/Help';
import { RPE_LABELS, rpeColor } from '../components/EffortPicker';
import { TYPE_COLOR, TYPE_LABEL } from './History';
import { toast } from '../toast';

type Leg = { name: string; date: string; distanceKm: string; gainM: string; routeFile: string };
type Draft = { name: string; kind: GoalKind; priority: 'A' | 'B' | 'C'; staged: boolean; legs: Leg[] };
const EMPTY_LEG: Leg = { name: '', date: '', distanceKm: '', gainM: '', routeFile: '' };
const EMPTY: Draft = { name: '', kind: 'MTB_MARATHON', priority: 'B', staged: false, legs: [{ ...EMPTY_LEG }] };
const PRIORITY: Record<string, string> = { A: 'A · la principal', B: 'B · importante', C: 'C · de preparación' };
const WEEKDAYS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const longDate = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
const shortDate = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });
const thisMonth = () => new Date().toISOString().slice(0, 7);
const shiftMonth = (month: string, delta: number) => {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};
const countdown = (days: number) => (days === 0 ? '¡Hoy!' : days === 1 ? 'Mañana' : days > 0 ? `Faltan ${days} días` : `Hace ${-days} días`);
const num = (text: string) => (text.trim() ? Number(text.replace(',', '.')) : null);
const stageLabel = (s: GoalStage) => `Etapa ${s.stageNo}${s.name ? ` · ${s.name}` : ''}`;
/** «4:12» or «4h 12» → seconds */
const parseTime = (text: string): number | null => {
  const m = text.trim().match(/^(\d{1,3})\s*[:h]\s*(\d{1,2})(?:\s*[:m]\s*(\d{1,2}))?\s*$/);
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3] ?? 0) : null;
};

/**
 * The races of the season: what the AI plans towards (coach/app/goals_store.py). A race of one day, or in stages, each
 * with its date and its GPX (chosen from the routes or uploaded here); a priority; after each day of racing, «¿Cómo
 * fue?» keeps the result, what the AI learns from. Below, the month: races and what was ridden each day.
 */
export function Calendar() {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [kinds, setKinds] = useState<Record<string, string>>({});
  const [races, setRaces] = useState<RaceRef[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [month, setMonth] = useState(thisMonth);
  const [grid, setGrid] = useState<CalendarMonth | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = () => api.goals().then((g) => { setGoals(g.goals); setKinds(g.kinds); setError(''); })
    .catch((e) => setError(`No se pudo leer el calendario: ${message(e)}`));
  const loadMonth = (m = month) => api.calendar(m).then(setGrid).catch((e) => setError(`No se pudo leer el mes: ${message(e)}`));
  const loadRaces = () => api.routes(0, 1).then((r) => setRaces(r.races)).catch(() => undefined);
  useEffect(() => { void load(); void loadRaces(); }, []);
  useEffect(() => { void loadMonth(month); }, [month]);

  const upcoming = (goals ?? []).filter((g) => g.daysToEnd >= 0 && g.status !== 'cancelled');
  const past = (goals ?? []).filter((g) => g.daysToEnd < 0 && !g.needsResult).reverse();
  // the days of racing already over without their result: a one-day race, or each stage
  const pending = (goals ?? []).flatMap((g) => (g.stages.length
    ? g.stages.filter((s) => s.needsResult).map((s) => ({ goal: g, stage: s as GoalStage | null }))
    : g.needsResult ? [{ goal: g, stage: null as GoalStage | null }] : []));

  const startNew = () => { setEditing(null); setDraft({ ...EMPTY, legs: [{ ...EMPTY_LEG }] }); };
  const startEdit = (g: Goal) => {
    setEditing(g.id);
    const leg = (date: string, km: number | null, gain: number | null, route: string | null, name = ''): Leg => ({
      name, date, distanceKm: km == null ? '' : String(km), gainM: gain == null ? '' : String(Math.round(gain)), routeFile: route ?? '' });
    setDraft({ name: g.name, kind: g.kind, priority: g.priority, staged: g.stages.length > 0,
      legs: g.stages.length ? g.stages.map((s) => leg(s.date, s.distanceKm, s.gainM, s.routeFile, s.name ?? ''))
        : [leg(g.eventDate, g.distanceKm, g.gainM, g.routeFile)] });
  };
  const setLeg = (i: number, changes: Partial<Leg>) => draft && setDraft({ ...draft, legs: draft.legs.map((l, j) => (j === i ? { ...l, ...changes } : l)) });
  /** A GPX chosen (or just uploaded) for a stage: its distance and climbing, and the name of the race if still empty. */
  const pickRoute = (i: number, race: RaceRef | undefined, file: string) => {
    if (!draft) return;
    const legs = draft.legs.map((l, j) => (j === i ? { ...l, routeFile: file,
      distanceKm: race ? String(Math.round((race.distanceKm ?? 0) * 10) / 10) : l.distanceKm,
      gainM: race ? String(Math.round(race.elevationGainM ?? 0)) : l.gainM } : l));
    setDraft({ ...draft, legs, name: draft.name || (!draft.staged && race?.name) || draft.name });
  };
  const toggleStages = (staged: boolean) => {
    if (!draft) return;
    const legs = staged && draft.legs.length < 2 ? [...draft.legs, { ...EMPTY_LEG }] : staged ? draft.legs : draft.legs.slice(0, 1);
    setDraft({ ...draft, staged, legs, kind: staged && draft.kind === 'MTB_MARATHON' ? 'MTB_STAGES' : draft.kind });
  };
  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const body: GoalInput = { name: draft.name, kind: draft.kind, priority: draft.priority };
      if (draft.staged) {
        body.stages = draft.legs.map((l) => ({ name: l.name || null, date: l.date, distanceKm: num(l.distanceKm), gainM: num(l.gainM),
          routeFile: l.routeFile || null }));
      } else {
        const l = draft.legs[0];
        Object.assign(body, { eventDate: l.date, distanceKm: num(l.distanceKm), gainM: num(l.gainM), routeFile: l.routeFile || null, stages: null });
      }
      const saved = await api.saveGoal(body, editing ?? undefined);
      toast.ok(editing ? `«${saved.name}» guardada.` : `«${saved.name}» añadida: ${countdown(saved.daysTo).toLowerCase()}.`);
      setDraft(null); setEditing(null);
      await load(); await loadMonth();
    } catch (e) { toast.error(`No se pudo guardar la prueba: ${message(e)}`); }
    finally { setBusy(false); }
  };
  const remove = async (g: Goal) => {
    if (!window.confirm(`¿Quitar «${g.name}» del calendario${g.result || g.stages.some((s) => s.result) ? ' (y sus resultados)' : ''}?`)) return;
    setBusy(true);
    try { await api.deleteGoal(g.id); toast.ok(`«${g.name}» quitada.`); await load(); await loadMonth(); }
    catch (e) { toast.error(`No se pudo quitar: ${message(e)}`); }
    finally { setBusy(false); }
  };
  const ready = draft && draft.name.trim() && draft.legs.every((l) => l.date) && (!draft.staged || draft.legs.length >= 2);

  return (
    <div className="admin">
      <div className="heading">
        <div>
          <p className="eyebrow">CALENDARIO</p>
          <h1>Tus pruebas <Help title="Para qué sirve el calendario">
            <p>Las pruebas que preparas, con su fecha, su recorrido (un GPX de Rutas, o súbelo aquí) y su prioridad: <strong>A</strong> la
              principal de la temporada, a la que llegar en tu mejor forma; <strong>B</strong> importante; <strong>C</strong> parte de la preparación.
              Una prueba por etapas lleva cada etapa con su fecha y su GPX.</p>
            <p>Con ellas la IA podrá planificar hacia cada prueba. Después de cada día de carrera, «¿Cómo fue?» guarda el resultado (si
              terminaste, tu tiempo, tu esfuerzo y la actividad de ese día): es lo que le enseña qué preparación funciona.</p>
          </Help></h1>
          <p className="muted">Lo que preparas y cómo te fue. Debajo, el mes con lo que entrenaste cada día.</p>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}
      <div className="admin-actions">
        <button className="primary" disabled={busy || draft !== null} onClick={startNew}>Añadir una prueba</button>
      </div>

      {draft && (
        <section className="panel">
          <div className="panel-heading"><h2>{editing ? 'Cambiar la prueba' : 'Nueva prueba'}</h2></div>
          <div className="profile-grid">
            <label className="field-block">Nombre
              <input maxLength={80} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Cuna de la Legión" />
            </label>
            <label className="field-block">Tipo
              <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as GoalKind })}>
                {Object.entries(kinds).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </label>
            <label className="field-block">Prioridad
              <select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value as Draft['priority'] })}>
                {(['A', 'B', 'C'] as const).map((p) => <option key={p} value={p}>{PRIORITY[p]}</option>)}
              </select>
            </label>
            <label className="switch stage-switch">
              <input type="checkbox" checked={draft.staged} onChange={(e) => toggleStages(e.target.checked)} />
              <span>Varias etapas</span>
            </label>
          </div>
          {draft.legs.map((leg, i) => (
            <LegEditor key={i} leg={leg} index={i} staged={draft.staged} races={races} busy={busy}
              onChange={(changes) => setLeg(i, changes)}
              onRoute={(race, file) => pickRoute(i, race, file)}
              onUploaded={async (file) => { const list = await api.routes(0, 1); setRaces(list.races); pickRoute(i, list.races.find((r) => r.file === file), file); }}
              onRemove={draft.legs.length > 2 ? () => setDraft({ ...draft, legs: draft.legs.filter((_, j) => j !== i) }) : undefined} />
          ))}
          {draft.staged && (
            <div className="admin-actions">
              <button disabled={busy || draft.legs.length >= 30} onClick={() => {
                const last = draft.legs[draft.legs.length - 1];
                const next = last.date ? new Date(new Date(`${last.date}T12:00:00`).getTime() + 86400000).toISOString().slice(0, 10) : '';
                setDraft({ ...draft, legs: [...draft.legs, { ...EMPTY_LEG, date: next }] });
              }}>+ Añadir etapa</button>
              <span className="tiny">La prueba va de la primera etapa a la última; sus km y su desnivel son la suma.</span>
            </div>
          )}
          <div className="admin-actions">
            <button className="primary" disabled={busy || !ready} onClick={() => void save()}>{editing ? 'Guardar' : 'Añadir'}</button>
            <button disabled={busy} onClick={() => { setDraft(null); setEditing(null); }}>Cancelar</button>
          </div>
        </section>
      )}

      {pending.length > 0 && <h2 className="subheading">¿Cómo fue?</h2>}
      {pending.map(({ goal, stage }) => <ResultForm key={`${goal.id}:${stage?.id ?? ''}`} goal={goal} stage={stage} onSaved={() => { void load(); }} />)}

      <h2 className="subheading">Próximas pruebas</h2>
      {goals && upcoming.length === 0 && <p className="muted">Todavía no hay pruebas. Añade la próxima que preparas.</p>}
      {upcoming.map((g, i) => <GoalCard key={g.id} goal={g} next={i === 0} busy={busy} onEdit={() => startEdit(g)} onRemove={() => void remove(g)} />)}

      <MonthGrid grid={grid} month={month} onMonth={setMonth} />

      {past.length > 0 && <h2 className="subheading">Pruebas pasadas</h2>}
      {past.map((g) => <GoalCard key={g.id} goal={g} busy={busy} onEdit={() => startEdit(g)} onRemove={() => void remove(g)} />)}
    </div>
  );
}

/** The date, GPX, distance and climbing of a one-day race, or of one stage. The GPX: one of the routes, or uploaded
 *  here (it is kept in Rutas too, to ride it or generate shorter versions). */
function LegEditor({ leg, index, staged, races, busy, onChange, onRoute, onUploaded, onRemove }: {
  leg: Leg; index: number; staged: boolean; races: RaceRef[]; busy: boolean;
  onChange: (changes: Partial<Leg>) => void; onRoute: (race: RaceRef | undefined, file: string) => void;
  onUploaded: (file: string) => Promise<void>; onRemove?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const upload = async (file: File) => {
    setUploading(true);
    try {
      const saved = await api.uploadRoute(file);
      toast.ok(`GPX «${saved.name}» guardado también en Rutas.`);
      await onUploaded(saved.file);
    } catch (e) { toast.error(`No se pudo subir «${file.name}»: ${message(e)}`); }
    finally { setUploading(false); if (input.current) input.current.value = ''; }
  };
  return (
    <div className={staged ? 'leg staged' : 'leg'}>
      {staged && <div className="leg-title"><strong>Etapa {index + 1}</strong>
        {onRemove && <button className="link-button" disabled={busy} onClick={onRemove}>quitar</button>}</div>}
      <div className="profile-grid">
        {staged && (
          <label className="field-block">Nombre de la etapa (opcional)
            <input maxLength={80} value={leg.name} placeholder={`Etapa ${index + 1}`} onChange={(e) => onChange({ name: e.target.value })} />
          </label>
        )}
        <label className="field-block">Fecha
          <input type="date" value={leg.date} onChange={(e) => onChange({ date: e.target.value })} />
        </label>
        <label className="field-block">Recorrido (GPX)
          <select value={leg.routeFile} onChange={(e) => onRoute(races.find((r) => r.file === e.target.value), e.target.value)}>
            <option value="">— sin GPX —</option>
            {races.map((r) => <option key={r.file} value={r.file}>{r.name}</option>)}
          </select>
        </label>
        <div className="field-block">o súbelo
          <input ref={input} type="file" accept=".gpx,application/gpx+xml" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
          <button disabled={busy || uploading} onClick={() => input.current?.click()}>{uploading ? 'Subiendo…' : 'Subir GPX'}</button>
        </div>
        <label className="field-block">Distancia
          <span><input inputMode="decimal" value={leg.distanceKm} onChange={(e) => onChange({ distanceKm: e.target.value })} /> km</span>
        </label>
        <label className="field-block">Desnivel +
          <span><input inputMode="numeric" value={leg.gainM} onChange={(e) => onChange({ gainM: e.target.value })} /> m</span>
        </label>
      </div>
    </div>
  );
}

function GoalCard({ goal: g, next = false, busy, onEdit, onRemove }: {
  goal: Goal; next?: boolean; busy: boolean; onEdit: () => void; onRemove: () => void;
}) {
  const staged = g.stages.length > 0;
  const running = staged && g.daysTo < 0 && g.daysToEnd >= 0;
  return (
    <article className={`panel goal-card priority-${g.priority} ${next ? 'next' : ''}`}>
      <div className="goal-main">
        <span className="goal-priority" title={PRIORITY[g.priority]}>{g.priority}</span>
        <div>
          <h2>{g.name}</h2>
          <p className="tiny">{staged ? `${shortDate(g.eventDate)} – ${longDate(g.endDate)} · ${g.stages.length} etapas` : longDate(g.eventDate)} · {g.kindLabel}
            {g.distanceKm ? ` · ${fmt(g.distanceKm, 0)} km` : ''}{g.gainM ? ` · ${fmt(g.gainM, 0)} m+` : ''}
            {g.routeName ? ` · GPX: ${g.routeName}` : ''}{g.status === 'cancelled' ? ' · cancelada' : ''}</p>
          {g.result && (
            <p className="tiny">{g.result.finished ? 'Terminada' : 'No terminada'}
              {g.result.timeSeconds ? ` en ${clock(g.result.timeSeconds)}` : ''}
              {g.result.rpe ? <> · esfuerzo <strong style={{ color: rpeColor(g.result.rpe) }}>{g.result.rpe}/10</strong></> : ''}
              {g.result.note ? ` · ${g.result.note}` : ''}</p>
          )}
        </div>
        <strong className="goal-countdown">{running ? 'En curso' : g.daysTo >= 0 ? countdown(g.daysTo) : ''}</strong>
      </div>
      {staged && (
        <ol className="stage-list">
          {g.stages.map((s) => (
            <li key={s.id}>
              <span>{stageLabel(s)}</span>
              <span>{shortDate(s.date)}{s.distanceKm ? ` · ${fmt(s.distanceKm, 0)} km` : ''}{s.gainM ? ` · ${fmt(s.gainM, 0)} m+` : ''}{s.routeName ? ` · GPX` : ''}</span>
              <span>{s.result ? `${s.result.finished ? '✓' : '✗'}${s.result.timeSeconds ? ` ${clock(s.result.timeSeconds)}` : ''}` : ''}</span>
            </li>
          ))}
        </ol>
      )}
      <div className="admin-actions">
        <button disabled={busy} onClick={onEdit}>Cambiar</button>
        <button className="danger" disabled={busy} onClick={onRemove}>Quitar</button>
      </div>
    </article>
  );
}

/** After a day of racing: did you finish, in how long, how hard, and which activity of that day it was. */
function ResultForm({ goal, stage, onSaved }: { goal: Goal; stage: GoalStage | null; onSaved: () => void }) {
  const day = stage?.date ?? goal.eventDate;
  const [finished, setFinished] = useState(true);
  const [time, setTime] = useState('');
  const [rpe, setRpe] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [activities, setActivities] = useState<DayActivity[]>([]);
  const [activity, setActivity] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.dayActivities(day).then((r) => {
      setActivities(r.activities);
      const longest = [...r.activities].sort((a, b) => (b.seconds ?? 0) - (a.seconds ?? 0))[0];
      if (longest) { setActivity(longest.id); if (longest.seconds) setTime(clock(longest.seconds)); }
    }).catch(() => undefined);
  }, [day]);
  const seconds = time ? parseTime(time) : null;
  const save = async () => {
    setBusy(true);
    try {
      await api.saveGoalResult(goal.id, { finished, timeSeconds: seconds, rpe, note: note || null, activityId: activity || null,
        ...(stage ? { stageNo: stage.stageNo } : {}) });
      toast.ok(`Resultado de ${stage ? `la ${stageLabel(stage).toLowerCase()} de ` : ''}«${goal.name}» guardado.`);
      onSaved();
    } catch (e) { toast.error(`No se pudo guardar el resultado: ${message(e)}`); }
    finally { setBusy(false); }
  };
  return (
    <article className="panel goal-card result-form">
      <div className="panel-heading"><h2>{goal.name}{stage ? ` · ${stageLabel(stage)}` : ''}</h2><span>{longDate(day).toUpperCase()}</span></div>
      <div className="profile-grid">
        <label className="field-block">¿Terminaste?
          <select value={finished ? 'yes' : 'no'} onChange={(e) => setFinished(e.target.value === 'yes')}>
            <option value="yes">Sí</option><option value="no">No</option>
          </select>
        </label>
        <label className="field-block">Tiempo (h:mm)
          <input value={time} placeholder="4:12" onChange={(e) => setTime(e.target.value)} />
        </label>
        <label className="field-block">Esfuerzo
          <select value={rpe ?? ''} onChange={(e) => setRpe(e.target.value ? Number(e.target.value) : null)}>
            <option value="">—</option>
            {Array.from({ length: 10 }, (_, i) => i + 1).map((v) => <option key={v} value={v}>{v} · {RPE_LABELS[v]}</option>)}
          </select>
        </label>
        <label className="field-block">La actividad de ese día
          <select value={activity} onChange={(e) => setActivity(e.target.value)}>
            <option value="">— ninguna —</option>
            {activities.map((a) => <option key={a.id} value={a.id}>{a.name ?? TYPE_LABEL[a.type as ActivityType] ?? a.type} · {clock(a.seconds)}</option>)}
          </select>
        </label>
      </div>
      <label className="field-block">Cómo fue (opcional, solo para ti)
        <input maxLength={500} value={note} placeholder="calambres en la última subida…" onChange={(e) => setNote(e.target.value)} />
      </label>
      {time && seconds == null && <p className="tiny warn">Escribe el tiempo como 4:12 (horas:minutos).</p>}
      <div className="admin-actions">
        <button className="primary" disabled={busy || (!!time && seconds == null)} onClick={() => void save()}>Guardar el resultado</button>
      </div>
    </article>
  );
}

/** One month, Monday first: the days of racing (by priority; a stage race, each stage) and what was done each day. */
function MonthGrid({ grid, month, onMonth }: { grid: CalendarMonth | null; month: string; onMonth: (m: string) => void }) {
  const cells = useMemo(() => {
    const [y, m] = month.split('-').map(Number);
    const first = new Date(y, m - 1, 1);
    const days = new Date(y, m, 0).getDate();
    const lead = (first.getDay() + 6) % 7;                 // Monday = 0
    return [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`)];
  }, [month]);
  const title = new Date(`${month}-15T12:00:00`).toLocaleDateString('es-ES', { month: 'long', year: 'numeric' });
  return (
    <section className="panel month">
      <div className="panel-heading">
        <h2 className="month-title">{title}</h2>
        <div className="month-nav">
          <button onClick={() => onMonth(shiftMonth(month, -1))} aria-label="Mes anterior">‹</button>
          <button onClick={() => onMonth(thisMonth())}>Hoy</button>
          <button onClick={() => onMonth(shiftMonth(month, 1))} aria-label="Mes siguiente">›</button>
        </div>
      </div>
      <div className="month-grid">
        {WEEKDAYS.map((d) => <span key={d} className="month-weekday">{d}</span>)}
        {cells.map((day, i) => {
          if (!day) return <span key={`x${i}`} />;
          const racing = (grid?.raceDays ?? []).filter((r) => r.date === day);
          const done = grid?.activities[day] ?? [];
          return (
            <div key={day} className={`month-day ${day === grid?.today ? 'today' : ''} ${racing.length ? 'has-goal' : ''}`}>
              <span className="month-number">{Number(day.slice(8))}</span>
              {racing.map((r) => (
                <span key={`${r.goalId}:${r.stageNo ?? ''}`} className={`month-goal priority-${r.priority}`}
                  title={`${r.name}${r.stageNo ? ` · etapa ${r.stageNo} de ${r.stages}` : ''} (${PRIORITY[r.priority]})`}>
                  {r.stageNo ? `E${r.stageNo} · ` : ''}{r.name}
                </span>
              ))}
              <span className="month-dots">
                {done.map((a) => <i key={a.id} style={{ background: TYPE_COLOR[a.type as ActivityType] ?? '#829d97' }}
                  title={`${a.name ?? TYPE_LABEL[a.type as ActivityType] ?? a.type} · ${clock(a.seconds)}${a.distanceKm ? ` · ${fmt(a.distanceKm, 1)} km` : ''}`} />)}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
