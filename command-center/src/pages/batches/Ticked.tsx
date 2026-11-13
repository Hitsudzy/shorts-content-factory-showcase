// Строка с `обратными кавычками` (строки фабрики и центра о входе Claude, CC-0177): то, что в
// кавычках, — моноширинным <code> без самих кавычек; непарная кавычка остаётся текстом.
import { Fragment } from 'react';

import { tickParts } from './login';

export function Ticked({ text }: { text: string }) {
  return (
    <>
      {tickParts(text).map((p, i) =>
        p.code ? (
          <code
            key={i}
            className="rounded-sm bg-[color-mix(in_srgb,var(--foreground)_7%,transparent)] px-1 font-mono text-[0.92em] [overflow-wrap:anywhere]"
          >
            {p.text}
          </code>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </>
  );
}
