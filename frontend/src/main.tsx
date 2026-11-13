import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Telemetry = {
  source: string; powerWatts: number; cadenceRpm: number; speedKph: number;
  elapsedSeconds: number; connected: boolean; status?: string; error?: string | null;
  heartRateBpm: number | null; heartRateConnected: boolean; heartRateStatus?: string;
  targetGradePercent?: number | null; estimatedDistanceKm?: number | null; mechanicalWorkKj?: number | null;
  zwiftLeftConnected?: boolean; zwiftRightConnected?: boolean; zwiftLeftStatus?: string; zwiftRightStatus?: string;
  virtualGear?: number; virtualGearCount?: number; virtualGearRelativeRatio?: number;
  lastButton?: string | null; controlStatus?: string; replayPlaying?: boolean;
  replaySpeed?: number; replayDurationSeconds?: number;
};
type Sample = { t: number; power: number | null; heart: number | null; cadence: number | null; speed: number | null; grade: number | null };
type Session = { durationSeconds: number; gradeKind: string; samples: Sample[] };
const fmt = (n: number | null | undefined, decimals=0) => n == null || !Number.isFinite(n) ? '—' : n.toLocaleString('es-ES', {maximumFractionDigits:decimals,minimumFractionDigits:decimals});
const clock = (n: number | null | undefined) => {const v=Math.floor(Math.max(0,n??0));return `${String(Math.floor(v/60)).padStart(2,'0')}:${String(v%60).padStart(2,'0')}`;};
const avg = (xs: number[]) => xs.length ? xs.reduce((a,b)=>a+b,0)/xs.length : null;

function Trace({points, field, color, unit, current, fullView}:{points:Sample[];field:'power'|'heart'|'cadence';color:string;unit:string;current:number;fullView:boolean}) {
  const valid=points.map(p=>p[field]).filter((v):v is number=>typeof v==='number' && Number.isFinite(v));
  if(!valid.length)return <div className="chart-empty">No hay datos disponibles</div>;
  const max=Math.max(1,...valid)*1.08,min=Math.min(0,...valid);
  const duration=Math.max(1,points[points.length-1]?.t??1), W=740,H=170,pad=12;
  const visible=fullView?points:points.filter(p=>p.t<=current);
  let d='',on=false;
  visible.forEach(p=>{
    const v=p[field]; if(v==null){on=false;return;}
    const x=pad+p.t/duration*(W-2*pad),y=H-pad-(v-min)/(max-min||1)*(H-2*pad);
    d+=`${on?'L':'M'}${x.toFixed(2)},${y.toFixed(2)} `;on=true;
  });
  const pointer=pad+Math.max(0,Math.min(1,current/duration))*(W-2*pad);
  return <div className="chart-wrapper"><svg viewBox={`0 0 ${W} ${H}`} aria-label={`Gráfico de ${field}`} role="img" preserveAspectRatio="none">
    {[.25,.5,.75].map(v=><line key={v} x1={pad} x2={W-pad} y1={H*v} y2={H*v} stroke="#2c4745" strokeDasharray="4 6"/>)}
    <path d={d} fill="none" stroke={color} strokeWidth="2.3" strokeLinejoin="round"/>
    <line x1={pointer} x2={pointer} y1="0" y2={H} stroke="#e0e8d8" strokeWidth="1.5" strokeDasharray="5 4"/>
  </svg><span>{fullView?'Sesión completa':'Progreso de sesión'} · {visible.filter(p=>p[field]!=null).length} de {valid.length} muestras · media total {fmt(avg(valid),1)} {unit}</span></div>;
}

function GradeProfile({points,current}:{points:Sample[];current:number}){
  const W=740,H=195,left=38,right=12,top=17,base=157;
  const duration=Math.max(1,points[points.length-1]?.t??1);
  const commands=points.filter(p=>p.grade!=null);
  const max=Math.max(3,...commands.map(p=>p.grade??0));
  const x=(t:number)=>left+t/duration*(W-left-right);
  const y=(v:number)=>base-v/Math.max(4,max+1)*(base-top);
  const first=commands[0]?.t??duration;
  const last=commands[commands.length-1]?.t??duration;
  // Exact commanded grade: horizontal plateaus with vertical transitions.
  // We deliberately do NOT interpolate recorded commands or infer an unknown grade.
  let commandPath='';
  commands.forEach((p,i)=>{
    const g=p.grade as number;
    if(i===0)commandPath=`M${x(p.t)},${y(g)}`;
    else if(g!==commands[i-1].grade)commandPath+=` H${x(p.t)} V${y(g)}`;
  });
  if(commands.length)commandPath+=` H${x(last)}`;
  const filled=commands.length?`${commandPath} L${x(last)},${base} L${x(first)},${base} Z`:'';
  const gradeAt=points.reduce<number|null>((g,p)=>p.t<=current?p.grade:g,null);
  return <div className="grade-profile">
    <div className="profile-top"><div><h2>Pendiente ordenada al rodillo</h2><p>Órdenes FTMS registradas · no es altitud GPS ni pendiente medida</p></div><strong>{fmt(gradeAt,1)} <small>%</small></strong></div>
    <svg role="img" aria-label="Pendiente ordenada al KICKR: escalones exactos sin suavizado" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <rect x={left} y={top} width={Math.max(0,x(first)-left)} height={base-top} fill="#ffffff" opacity=".035"/>
      {[0,1,2,3,4].map(g=><g key={g}><line x1={left} x2={W-right} y1={y(g)} y2={y(g)} stroke="#38504b" strokeDasharray="4 5"/><text x={left-8} y={y(g)+4} textAnchor="end" fill="#94aaa5" fontSize="11">{g}%</text></g>)}
      {filled&&<path d={filled} fill="#81d8b2" opacity=".15"/>}
      {commandPath&&<path d={commandPath} stroke="#81d8b2" strokeWidth="3" fill="none" strokeLinejoin="miter"/>}
      <line x1={x(Math.max(0,Math.min(current,duration)))} x2={x(Math.max(0,Math.min(current,duration)))} y1={top} y2={base} stroke="#f6c180" strokeWidth="2" strokeDasharray="5 4"/>
      {[0,2,4,6,8,10].map(t=><text key={t} x={x(duration*t/10)} y={base+20} fontSize="11" textAnchor="middle" fill="#9eafa9">{t} min</text>)}
    </svg>
    <div className="profile-legend"><span>▨ Sin orden registrada antes de ~5 min</span><span>— Escalones de pendiente ordenada</span><span>│ Posición actual</span></div>
  </div>;
}

function App(){
  const [data,setData]=useState<Telemetry|null>(null);
  const [session,setSession]=useState<Session|null>(null);
  const [history,setHistory]=useState<Sample[]>([]);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [fullView,setFullView]=useState(false);
  const replay=data?.source==='REPLAY';
  useEffect(()=>{
    let alive=true;
    async function poll(){try{const r=await fetch('/api/trainer/telemetry',{cache:'no-store'});if(!r.ok)throw new Error(`API HTTP ${r.status}`);const d:Telemetry=await r.json();if(!alive)return;setData(d);setError('');
      if(d.source!=='REPLAY'&&d.connected)setHistory(prev=>[...prev.filter(x=>x.t!==d.elapsedSeconds),{t:d.elapsedSeconds,power:d.powerWatts,heart:d.heartRateBpm,cadence:d.cadenceRpm,speed:d.speedKph,grade:d.targetGradePercent??null}].slice(-600));
    }catch(e){if(alive)setError(String(e));}}
    void poll();const timer=window.setInterval(()=>void poll(),1000);return()=>{alive=false;clearInterval(timer);};
  },[]);
  useEffect(()=>{if(!replay)return;let alive=true;fetch('/api/trainer/replay/session',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json();}).then(s=>{if(alive)setSession(s);}).catch(e=>{if(alive)setError(`Histórico: ${e}`);});return()=>{alive=false;};},[replay]);
  const points=replay?(session?.samples??[]):history;
  const seconds=data?.elapsedSeconds??0;
  const duration=session?.durationSeconds??data?.replayDurationSeconds??600;
  const windowSamples=useMemo(()=>points.filter(x=>x.t<=seconds&&x.t>seconds-3&&x.power!=null).map(x=>x.power as number),[points,seconds]);
  const power3=avg(windowSamples);
  const currentGrade=data?.targetGradePercent??null;
  const shownGear=data?.virtualGear??12;
  async function command(endpoint:string,body:object){setBusy(true);try{const r=await fetch(`/api/trainer/replay/${endpoint}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw new Error(`HTTP ${r.status}`);setError('');}catch(e){setError(`Control REPLAY: ${String(e)}`);}finally{setBusy(false);}}
  return <main>
    <header><div className="brand"><span className="logo">↗</span><div><strong>AI CYCLING COACH</strong><small>TRAINING LAB · v4.2.1</small></div></div><span className={`mode ${replay?'replay':''}`}>{replay?'REPLAY · HISTÓRICO':data?.source??'CONECTANDO'}</span></header>
    <div className="heading"><div><p className="eyebrow">PANEL DE ENTRENAMIENTO</p><h1>Tu sesión, en detalle</h1><p className="muted">Datos reales, perfiles y marchas virtuales · control físico deshabilitado</p></div><div className="timer"><small>TIEMPO DE SESIÓN</small><strong>{clock(seconds)}</strong><small>de {clock(duration)}</small></div></div>
    {error&&<div className="alert">{error}</div>}
    <div className="statuses"><span className={data?.connected?'ok':'off'}>● Telemetría: {data?.status??'Esperando'}</span><span className={data?.heartRateConnected?'ok':'off'}>● HR50: {data?.heartRateStatus??'Esperando'}</span><span className={data?.zwiftLeftConnected?'ok':'off'}>● Zwift izq.: {data?.zwiftLeftStatus??'Sin datos'}</span><span className={data?.zwiftRightConnected?'ok':'off'}>● Zwift der.: {data?.zwiftRightStatus??'Sin datos'}</span></div>
    <section className="metrics">
      <article className="metric emphasis"><span>POTENCIA</span><div><strong>{fmt(data?.powerWatts)}</strong><em>W</em></div><small>Suavizada 3 s: {fmt(power3)} W</small></article>
      <article className="metric"><span>PULSO</span><div><strong>{fmt(data?.heartRateBpm)}</strong><em>ppm</em></div><small>iGPSPORT HR50</small></article>
      <article className="metric"><span>CADENCIA</span><div><strong>{fmt(data?.cadenceRpm)}</strong><em>rpm</em></div><small>Revoluciones/min</small></article>
      <article className="metric"><span>VELOCIDAD</span><div><strong>{fmt(data?.speedKph,1)}</strong><em>km/h</em></div><small>Velocidad virtual</small></article>
      <article className="metric slope-metric"><span>PENDIENTE ORDENADA</span><div><strong>{fmt(currentGrade,1)}</strong><em>%</em></div><small>{currentGrade==null?'Sin orden en esta fase':'No es pendiente medida'}</small></article>
    </section>
    {replay&&<section className="panel replay-panel"><div className="panel-heading"><h2>Reproductor de sesión</h2><span>{data?.replayPlaying?'REPRODUCIENDO':'PAUSADO / FINALIZADO'}</span></div>
      <input className="timeline" aria-label="Posición de la reproducción" type="range" min={0} max={duration} step={1} value={Math.min(seconds,duration)} onChange={e=>void command('control',{action:'seek',value:Number(e.target.value)})}/>
      <div className="replay-actions"><div><button disabled={busy} onClick={()=>void command('control',{action:data?.replayPlaying?'pause':'play'})}>{data?.replayPlaying?'⏸ Pausar':'▶ Reproducir'}</button><button disabled={busy} onClick={()=>void command('control',{action:'restart'})}>↺ Reiniciar</button><button disabled={busy} onClick={()=>void command('control',{action:'seek',value:300})}>Ir al minuto 5</button></div>
        <label>Velocidad <select disabled={busy} value={data?.replaySpeed??1} onChange={e=>void command('control',{action:'speed',value:Number(e.target.value)})}><option value={0.5}>0,5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label></div>
    </section>}
    <section className="panel"><GradeProfile points={points} current={seconds}/></section>
    {replay&&<div className="display-mode"><span>Visualización de gráficas</span><div><button className={!fullView?'selected':''} onClick={()=>setFullView(false)}>Durante la sesión</button><button className={fullView?'selected':''} onClick={()=>setFullView(true)}>Análisis completo</button></div></div>}
    <div className="workspace"><section className="left">
      <article className="panel"><div className="panel-heading"><h2>Potencia</h2><span>{replay?(fullView?'ANÁLISIS COMPLETO':'PROGRESO REPLAY'):'HISTÓRICO EN DIRECTO'}</span></div><Trace points={points} field="power" color="#6ce8af" unit="W" current={seconds} fullView={replay&&fullView}/></article>
      <article className="panel"><div className="panel-heading"><h2>Frecuencia cardíaca</h2><span>{replay?(fullView?'ANÁLISIS COMPLETO':'PROGRESO REPLAY'):'HISTÓRICO EN DIRECTO'}</span></div><Trace points={points} field="heart" color="#fb8c83" unit="ppm" current={seconds} fullView={replay&&fullView}/></article>
      <article className="panel"><div className="panel-heading"><h2>Cadencia</h2><span>{replay?(fullView?'ANÁLISIS COMPLETO':'PROGRESO REPLAY'):'HISTÓRICO EN DIRECTO'}</span></div><Trace points={points} field="cadence" color="#aab5ff" unit="rpm" current={seconds} fullView={replay&&fullView}/></article>
    </section><section className="right">
      <article className="panel control-panel"><div className="panel-heading"><h2>Marchas virtuales</h2><span>SIMULACIÓN · NO ACTÚA SOBRE KICKR</span></div>
        <div className="gear-display"><span>Marcha</span><strong>{shownGear}<small> / 24</small></strong></div>
        <div className="gear-buttons"><button disabled={!replay||busy||shownGear<=1} onClick={()=>void command('gear',{delta:-1})}>− Más fácil</button><button disabled={!replay||busy||shownGear>=24} onClick={()=>void command('gear',{delta:1})}>+ Más duro</button></div>
        <p className="tiny">Relación relativa ilustrativa: {fmt(data?.virtualGearRelativeRatio,2)}× · NO reproduce la tabla oficial de Zwift.</p>
        <p className="tiny">Último botón: {data?.lastButton??'ninguno'} · Marcha actual: {shownGear}</p>
        <p className="tiny">Zwift izq.: {data?.zwiftLeftConnected?'conectado':'sin conexión'} · Zwift der.: {data?.zwiftRightConnected?'conectado':'sin conexión'}</p>
        <p className="tiny">Los botones físicos +/− cambian la marcha visual al conectarse. Pulsa y comprueba el número y el último botón recibido. En REPLAY no se envían órdenes al rodillo.</p>
      </article>
      <article className="panel stats"><h2>Sesión</h2><div><span>Distancia estimada</span><strong>{fmt(data?.estimatedDistanceKm,2)} km</strong></div><div><span>Trabajo mecánico</span><strong>{fmt(data?.mechanicalWorkKj,1)} kJ</strong></div><div><span>Máxima pendiente ordenada</span><strong>{fmt(points.reduce<number|null>((a,p)=>p.grade==null?a:Math.max(a??p.grade,p.grade),null),1)} %</strong></div><div><span>Fuente</span><strong>{data?.source??'—'}</strong></div></article>
    </section></div>
    <footer>La v4.2 no implementa cambios físicos de marcha. Las marchas y sus relaciones son una maqueta matemática para validar eventos y UI. Datos históricos locales; ninguna orden BLE desde REPLAY.</footer>
  </main>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
