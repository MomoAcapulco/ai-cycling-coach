import { useEffect, useState } from 'react';
import { dismiss, subscribe, type Toast } from '../toast';

/** The floating messages, bottom right (full width on a phone), above everything and independent of the scroll. */
export function Toasts() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => subscribe(setItems), []);
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'}>
          <span>{t.text}</span>
          <button className="toast-close" aria-label="Cerrar" onClick={() => dismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
