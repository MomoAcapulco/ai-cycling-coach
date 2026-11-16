import type { ActiveRoute, Activity, HistoryWeek, LoadReport, RouteSummary, WorkoutLibrary, FtpAdvice, GeneratedRoute, SessionFeedback } from './types';
import type { AdminState, DevicesState, ProfileState, Recording, RiderProfile, Session, SessionSummary, Settings, Telemetry } from './types';

const BASE = '/api/trainer';

/** Error carrying the HTTP status and the adapter's own message when there is one. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, { cache: 'no-store', ...init });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, describeError(response.status, body));
  }
  return body as T;
}

/** The Java API wraps adapter errors as {error, adapterStatus, adapterResponse}; Python sends HTML. */
function describeError(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const { error, adapterResponse } = body as { error?: string; adapterResponse?: string };
    const detail = adapterResponse ? extractMessage(adapterResponse) : '';
    if (detail) return detail;
    if (error) return error;
  }
  return `HTTP ${status}`;
}

function extractMessage(html: string): string {
  const match = html.match(/<p>Message:\s*([^<]*)<\/p>/i);
  return (match ? match[1] : html).trim().slice(0, 300);
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/** Lists come a page at a time (the server counts the rest). */
export const PAGE = 20;
export type Page = { total: number; limit: number | null; offset: number };
export type RaceRef = Pick<RouteSummary, 'file' | 'name' | 'distanceKm' | 'elevationGainM' | 'maxGradePercent'>;
export type RoutesPage = Page & { routes: RouteSummary[]; races: RaceRef[]; current: string | null; available: boolean };

export const api = {
  telemetry: () => request<Telemetry>('/telemetry'),
  replaySession: () => request<Session>('/replay/session'),
  replayControl: (action: string, value?: number) => request('/replay/control', json({ action, value })),
  gear: (delta: 1 | -1) => request('/gear', json({ delta })),
  grade: (gradePercent: number) =>
    request<{ targetGradePercent: number; effectiveGradePercent: number }>('/grade', json({ gradePercent })),
  adminState: () => request<AdminState>('/admin/settings'),
  saveSettings: (changes: Partial<Settings>) => request<AdminState>('/admin/settings', json(changes)),
  resetSettings: () => request<AdminState>('/admin/settings/reset', { method: 'POST' }),
  recordings: () => request<{ recordings: Recording[]; current: string | null }>('/admin/recordings'),
  uploadRecording: (file: File) =>
    request<Recording>(`/admin/recordings?name=${encodeURIComponent(file.name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: file,
    }),
  profile: () => request<ProfileState>('/admin/profile'),
  saveProfile: (profile: Partial<RiderProfile>) => request<ProfileState>('/admin/profile', json(profile)),
  sessionAction: (action: 'start' | 'pause' | 'resume' | 'finish') =>
    request<Telemetry & Partial<SessionSummary>>(`/session/${action}`, { method: 'POST' }),
  sessions: (offset = 0, hideTests = true, limit = PAGE) =>
    request<Page & { sessions: SessionSummary[]; tests: number }>(`/sessions?limit=${limit}&offset=${offset}${hideTests ? '&tests=hide' : ''}`),
  devices: () => request<DevicesState>('/devices'),
  forgetDevice: (role: string, address?: string) =>
    request<DevicesState>(`/devices/${role}${address ? `?address=${encodeURIComponent(address)}` : ''}`, { method: 'DELETE' }),
  useDevice: (role: string, address: string) => request<DevicesState>(`/devices/${role}/use`, json({ address })),
  startRampTest: () => request<Telemetry>('/workout/ramp/start', { method: 'POST' }),
  stopWorkout: () => request<Telemetry>('/workout/stop', { method: 'POST' }),
  saveTestFtp: () => request<{ ftpWatts: number }>('/workout/ftp/save', { method: 'POST' }),
  workoutLibrary: () => request<WorkoutLibrary>('/workout/library'),
  startWorkout: (id: string) => request<Telemetry>('/workout/structured/start', json({ id })),
  clearWorkout: () => request<{ workout: null }>('/workout/clear', { method: 'POST' }),
  history: (offset = 0, type: string | null = null, limit = PAGE) =>
    request<Page & { activities: Activity[]; counts: Record<string, number>; types: Record<string, number>; type: string | null }>(
      `/history?limit=${limit}&offset=${offset}${type ? `&type=${encodeURIComponent(type)}` : ''}`),
  historyLoad: (days = 180) => request<LoadReport>(`/history/load?days=${days}`),
  ftpAdvice: () => request<FtpAdvice>('/history/ftp'),
  historyWeeks: (type: string | null = null) =>
    request<{ weeks: HistoryWeek[] }>(`/history/weeks${type ? `?type=${encodeURIComponent(type)}` : ''}`),
  routes: (offset = 0, limit = PAGE) => request<RoutesPage>(`/routes?limit=${limit}&offset=${offset}`),
  uploadRoute: (file: File) =>
    request<RouteSummary>(`/routes?name=${encodeURIComponent(file.name)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/gpx+xml' }, body: file,
    }),
  route: () => request<ActiveRoute>('/route'),
  deleteRoute: (file: string) => request<{ deleted: string }>(`/routes/${encodeURIComponent(file)}`, { method: 'DELETE' }),
  deleteSession: (session: string) => request<{ deleted: string }>(`/sessions/${session}`, { method: 'DELETE' }),
  routeReplay: (file: string) => request<{ replayFile: string }>(`/routes/${encodeURIComponent(file)}/replay`, json({})),
  renameRoute: (file: string, name: string) => request<RouteSummary>('/routes/rename', json({ file, name })),
  sessionFeedback: (session: string, body: { rpe: number | null; note: string }) =>
    request<SessionFeedback>(`/sessions/${session}/feedback`, json(body)),
  generateRoute: (body: object) => request<GeneratedRoute>('/routes/generate', json(body)),
  routePreview: (file: string) =>
    request<RouteSummary & { profile: { d: number; e: number; g: number }[] }>(`/routes/${encodeURIComponent(file)}`),
  startRoute: (file: string) => request<RouteSummary>('/route/start', json({ file })),
  stopRoute: () => request<{ active: false }>('/route/stop', { method: 'POST' }),
};

/** URL that downloads a finished session's file (the browser saves it). */
export const sessionFileUrl = (name: string) => `${BASE}/sessions/${encodeURIComponent(name)}`;
