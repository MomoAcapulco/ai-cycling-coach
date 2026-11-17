import { useEffect, useState } from 'react';
import { api } from '../api';
import { fmt } from '../format';
import type { FtpAdvice } from '../types';
import { Help } from './Help';
import { exitReplay } from '../liveMode';
import { toast } from '../toast';

const SECONDS = (s: number) => (s < 60 ? `${s} s` : `${s / 60} min`);
const date = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });

/**
 * The FTP notice (coach/history/ftp_model.py): it proposes, the rider decides. «raise» and «set» have a button that
 * saves the estimate as the FTP; «test» sends to the FTP test. ``always`` shows it also when all is fine.
 */
export function FtpNotice({ always = false, replay = false, onChanged }: { always?: boolean; replay?: boolean; onChanged?: () => void }) {
  const [advice, setAdvice] = useState<FtpAdvice | null>(null);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(false);
  const load = () => api.ftpAdvice().then(setAdvice).catch(() => undefined);
  useEffect(() => { void load(); }, []);
  if (!advice || hidden || (advice.kind === 'ok' && !always)) return null;

  const save = async (ftp: number) => {
    setBusy(true);
    try { await api.saveProfile({ ftpWatts: ftp, ftpSource: 'estimate' }); toast.ok(`FTP guardado: ${ftp} W.`); await load(); onChanged?.(); }
    catch (e) { toast.error(`No se pudo guardar el FTP: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  const where = advice.estimateFrom === 'indoor' ? 'en el rodillo' : 'en la calle (×0,95 para el rodillo)';
  const weeks = Math.round(advice.maxEffortDays / 7);
  const text = {
    raise: <>Has rendido por encima de tu FTP: tus esfuerzos {where} de las últimas {Math.round(advice.windowDays / 7)} semanas
      dan <strong>{advice.suggestedFtp} W</strong> (tienes {advice.ftp} W).</>,
    set: <>No tienes FTP en tu perfil. Con tus esfuerzos {where} sale <strong>{advice.suggestedFtp} W</strong>; el test de FTP lo medirá mejor.</>,
    test: advice.reason === 'no_ftp' ? <>No tienes FTP ni esfuerzos recientes para estimarlo: haz el test de FTP.</>
      : advice.reason === 'falling' ? <>Tus esfuerzos recientes dan {advice.estimateFtp} W, bastante menos que tu FTP ({advice.ftp} W). Puede ser
        cansancio o que el FTP esté alto: no se baja solo; un test lo aclara.</>
        : <>{advice.lastMaxEffort ? `Tu último esfuerzo máximo fue hace ${advice.lastMaxEffort.daysAgo} días` : 'No hay esfuerzos máximos recientes'}:
          los entrenamientos por debajo del umbral no dicen cuánto puedes dar. Toca test de FTP (cada {weeks} semanas como mucho).</>,
    ok: <>Tu FTP ({advice.ftp} W) está al día{advice.estimateFtp ? `: tus esfuerzos recientes dan ${advice.estimateFtp} W` : ''}
      {advice.lastMaxEffort ? `, último esfuerzo máximo hace ${advice.lastMaxEffort.daysAgo} días` : ''}.</>,
  }[advice.kind];

  return (
    <section className={`panel ftp-notice ${advice.kind}`}>
      <div className="panel-heading"><h2>FTP <Help title="De dónde sale tu FTP">
        <p>Con tus mejores esfuerzos de las últimas {Math.round(advice.windowDays / 7)} semanas, de dos formas, y se queda la más alta
          (un esfuerzo que no fue a tope solo puede quedarse corto): el modelo de potencia crítica con los de 3 a 30 minutos (su
          potencia para 1 hora) y el mejor esfuerzo de 20 a 60 minutos llevado a 1 hora (20 min → 95 %, como el cálculo clásico).
          Nunca se cambia solo, y nunca se propone bajarlo: los entrenamientos suaves no dicen cuánto puedes dar. Rodillo y calle
          van aparte (en el rodillo suele salir un 5–10 % menos).</p>
        {([['Rodillo', advice.indoor], ['Calle', advice.outdoor]] as const).map(([label, e]) => (
          <p key={label}>{label}: {e ? <>{e.ftp} W ({e.method === 'cp' ? 'modelo' : `esfuerzo de ${(e.seconds ?? 0) / 60} min`}{e.modelFtp != null
            ? ` · modelo ${e.modelFtp} W, CP ${e.cp} W, W′ ${fmt((e.wPrime ?? 0) / 1000, 1)} kJ` : ''}{e.singleFtp != null ? ` · mejor esfuerzo largo ${e.singleFtp} W` : ''}) ·
            {' '}{e.efforts.filter((x) => [180, 300, 600, 1200].includes(x.seconds)).map((x) => `${SECONDS(x.seconds)} ${fmt(x.w, 0)} W (${date(x.date)})`).join(' · ')}</>
            : 'sin esfuerzos con potencia en este tiempo'}</p>
        ))}
        {advice.lastTest && <p>Último test de FTP: {date(advice.lastTest.date)}.</p>}
      </Help></h2><span>{advice.kind === 'ok' ? 'AL DÍA' : advice.kind === 'test' ? 'TOCA TEST' : 'PROPUESTA'}</span></div>
      <p>{text}</p>
      <div className="admin-actions">
        {(advice.kind === 'raise' || advice.kind === 'set') && advice.suggestedFtp && (
          <button className="primary" disabled={busy} onClick={() => void save(advice.suggestedFtp as number)}>
            {advice.kind === 'raise' ? `Subir a ${advice.suggestedFtp} W` : `Usar ${advice.suggestedFtp} W`}</button>
        )}
        {advice.kind !== 'ok' && (replay
          ? <button disabled={busy} onClick={() => { setBusy(true); exitReplay().then(() => { window.location.hash = '#/'; }).catch((e) => toast.error(`No se pudo salir del replay: ${e instanceof Error ? e.message : e}`)).finally(() => setBusy(false)); }}>
              Salir del replay y hacer el test de FTP</button>
          : <a className="button-link" href="#/">Test de FTP (Panel)</a>)}
        {advice.kind !== 'ok' && !always && <button disabled={busy} onClick={() => setHidden(true)}>Ahora no</button>}
      </div>
    </section>
  );
}
