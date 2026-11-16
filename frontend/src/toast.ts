/**
 * Floating messages: they show where the user is looking, whatever the scroll, instead of at the top of the page.
 * Errors stay until closed (they explain what to do); confirmations go away on their own.
 */
export type ToastKind = 'error' | 'ok';
export type Toast = { id: number; kind: ToastKind; text: string };

const OK_MS = 6000;
const MAX = 4;
let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<(t: Toast[]) => void>();
const emit = () => listeners.forEach((l) => l(toasts));

export function dismiss(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

function show(kind: ToastKind, text: string) {
  toasts = toasts.filter((t) => t.text !== text);   // the same message twice: once, moved to the end
  const t = { id: nextId++, kind, text };
  toasts = [...toasts, t].slice(-MAX);
  emit();
  if (kind === 'ok') setTimeout(() => dismiss(t.id), OK_MS);
}

export const toast = {
  error: (text: string) => show('error', text),
  ok: (text: string) => show('ok', text),
  clear: () => { toasts = []; emit(); },
};

export function subscribe(listener: (t: Toast[]) => void) {
  listeners.add(listener);
  listener(toasts);
  return () => { listeners.delete(listener); };
}

/** Message of anything thrown, for «No se pudo …: <message>». */
export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
