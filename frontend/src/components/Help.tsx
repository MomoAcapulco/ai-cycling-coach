import { useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

/**
 * The explanation of a section or a field: an ⓘ right next to its title or its label, opening a window over the
 * page (a native <dialog>: Esc, the × or a click outside closes it, and the page does not move). The window goes to
 * <body> (a portal), so it can sit inside a heading or a label without taking their styles or their clicks.
 */
export function Help({ children, title }: { children: ReactNode; title: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = () => dialog.current?.close();
  return (
    <>
      <button type="button" className="help-icon" aria-haspopup="dialog" aria-label={title} title={title}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); dialog.current?.showModal(); }}>ⓘ</button>
      {createPortal(
        <dialog ref={dialog} className="help-dialog" aria-label={title}
          onClick={(e) => { e.stopPropagation(); if (e.target === e.currentTarget) close(); }}>
          <div className="help-dialog-body">
            <div className="help-dialog-heading">
              <h2>{title}</h2>
              <button type="button" className="toast-close" aria-label="Cerrar" onClick={close}>×</button>
            </div>
            <div className="help-dialog-text">{children}</div>
          </div>
        </dialog>,
        document.body,
      )}
    </>
  );
}
