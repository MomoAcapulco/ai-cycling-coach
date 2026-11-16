import type { Page } from '../api';

/** «← Más recientes · 21–40 de 57 · Anteriores →» under a list that comes a page at a time. */
export function Pager({ page, onPage, label = 'elementos' }: { page: Page | null; onPage: (offset: number) => void; label?: string }) {
  if (!page || page.limit == null || page.total <= page.limit) return null;
  const { total, limit, offset } = page;
  const last = Math.min(total, offset + limit);
  return (
    <nav className="pager" aria-label="Páginas">
      <button disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>← Más recientes</button>
      <span>{offset + 1}–{last} de {total} {label}</span>
      <button disabled={last >= total} onClick={() => onPage(offset + limit)}>Anteriores →</button>
    </nav>
  );
}
