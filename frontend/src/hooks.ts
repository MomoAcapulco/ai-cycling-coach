import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { Sample, Telemetry } from './types';
import { rememberLiveMode } from './liveMode';

const POLL_MS = 1000;
const MAX_BACKOFF_MS = 8000;
const LIVE_HISTORY = 3600; // one hour of 1 Hz samples

/**
 * Polls /telemetry every second. On errors it backs off (1, 2, 4, 8 s) instead of hammering a
 * stopped adapter, and recovers by itself. Live (non-replay) samples are kept as history.
 *
 * The history is THE SESSION: it starts empty at «Iniciar sesión» and its time axis is the session time (pauses
 * excluded). Without a session nothing is recorded (nothing was asked for). The last session stays on screen after
 * «Terminar» until a new one starts.
 */
export function useTelemetry() {
  const [data, setData] = useState<Telemetry | null>(null);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<Sample[]>([]);
  const lastMode = useRef<string | undefined>(undefined);
  const lastSession = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    let delay = POLL_MS;
    const poll = async () => {
      try {
        const d = await api.telemetry();
        if (!alive) return;
        delay = POLL_MS;
        setData(d);
        setError('');
        rememberLiveMode(d.mode);
        if (d.mode !== lastMode.current) {
          // A different source (changed in Ajustes) starts a new history.
          lastMode.current = d.mode;
          setHistory([]);
        }
        const inSession = d.sessionState === 'RUNNING' || d.sessionState === 'PAUSED';
        if (inSession && d.session && d.session !== lastSession.current) {
          setHistory([]);                     // a new session: its charts start empty, at 0:00
        }
        if (inSession) lastSession.current = d.session ?? null;   // after «Terminar» it remembers the last one
        if (d.source !== 'REPLAY' && d.connected && d.sessionState === 'RUNNING') {
          const sample: Sample = {
            t: Math.round(d.sessionElapsedSeconds ?? 0), power: d.powerWatts, target: d.targetPowerW ?? null, heart: d.heartRateBpm, cadence: d.cadenceRpm,
            speed: d.rideSpeedKph ?? d.speedKph, grade: d.roadGradePercent ?? d.targetGradePercent ?? null,
            effective: d.effectiveGradePercent ?? null, distance: d.rideDistanceKm ?? null, altitude: d.altitudeM ?? null,
          };
          setHistory((prev) => [...prev.filter((x) => x.t !== sample.t), sample].slice(-LIVE_HISTORY));
        }
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        delay = Math.min(delay * 2, MAX_BACKOFF_MS);
      }
      if (alive) timer = window.setTimeout(poll, delay);
    };
    void poll();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  return { data, error, history };
}

export type Route = 'panel' | 'entrenamientos' | 'rutas' | 'sesiones' | 'historial' | 'ajustes';

/** Minimal hash router: #/rutas, #/sesiones, #/ajustes, anything else is the panel. */
export function useRoute(): Route {
  const read = (): Route => {
    const page = window.location.hash.replace(/^#\/?/, '').split('/')[0];   // #/ajustes/perfil → ajustes
    return page === 'ajustes' || page === 'sesiones' || page === 'rutas' || page === 'historial' || page === 'entrenamientos' ? page : 'panel';
  };
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
