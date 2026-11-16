import type { ReactNode } from 'react';

/** The explanations, folded: the screen shows the numbers; how it works is one click away. */
export function Help({ children, label = '¿Cómo funciona?' }: { children: ReactNode; label?: string }) {
  return <details className="help"><summary>{label}</summary><div>{children}</div></details>;
}
