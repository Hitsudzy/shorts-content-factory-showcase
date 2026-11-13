// «Сырой JSON»: файл канала как есть, с подсветкой и проверкой записи на лету (CodeMirror 6,
// без сети). Грузится отдельным куском — только когда открыли эту вкладку.
import { json } from '@codemirror/lang-json';
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { linter, lintGutter, type Diagnostic } from '@codemirror/lint';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { tags } from '@lezer/highlight';
import { basicSetup } from 'codemirror';
import { useEffect, useRef } from 'react';

import { jsonProblems } from './fields';

// Цвета — токены темы «Кинозал»: ключи — акцентом-текстом, строки — «готово», числа — «холд».
const highlight = HighlightStyle.define([
  { tag: tags.propertyName, color: 'var(--primary-text)' },
  { tag: tags.string, color: 'var(--success)' },
  { tag: tags.number, color: 'var(--warning)' },
  { tag: [tags.bool, tags.null], color: 'var(--danger)' },
  {
    tag: [tags.brace, tags.squareBracket, tags.separator, tags.punctuation],
    color: 'var(--muted-foreground)',
  },
]);

const theme = EditorView.theme({
  '&': {
    backgroundColor: 'var(--background)',
    color: 'var(--foreground)',
    fontSize: '12.5px',
    border: '1px solid var(--input)',
    borderRadius: 'var(--radius-sm, 4px)',
    maxHeight: '70vh',
    minHeight: '320px',
  },
  '&.cm-focused': { outline: '2px solid var(--ring)', outlineOffset: '1px' },
  '.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: '1.55', overflow: 'auto' },
  '.cm-content': { caretColor: 'var(--primary-text)' },
  '.cm-gutters': {
    backgroundColor: 'var(--card)',
    color: 'var(--muted-foreground)',
    borderRight: '1px solid var(--border)',
  },
  '.cm-activeLine, .cm-activeLineGutter': {
    backgroundColor: 'color-mix(in srgb, var(--primary) 7%, transparent)',
  },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection': {
    backgroundColor: 'color-mix(in srgb, var(--primary) 28%, transparent) !important',
  },
  '.cm-cursor': { borderLeftColor: 'var(--primary-text)' },
  '.cm-tooltip': {
    backgroundColor: 'var(--popover)',
    color: 'var(--popover-foreground)',
    border: '0',
    fontFamily: 'var(--font-sans)',
  },
  '.cm-panels': { backgroundColor: 'var(--card)', color: 'var(--foreground)' },
  '.cm-searchMatch': { backgroundColor: 'color-mix(in srgb, var(--warning) 30%, transparent)' },
  '.cm-matchingBracket': { backgroundColor: 'color-mix(in srgb, var(--primary) 25%, transparent)' },
});

/** Ошибки записи — по-русски (тот же разбор, что и под редактором). */
const ruLinter = linter(
  (view): Diagnostic[] =>
    jsonProblems(view.state.doc.toString()).map((p) => ({
      from: Math.min(p.offset, view.state.doc.length),
      to: Math.min(p.offset + Math.max(p.length, 1), view.state.doc.length),
      severity: 'error',
      message: `Строка ${p.line}, столбец ${p.column}: ${p.text}`,
    })),
  { delay: 300 },
);

export default function RawEditor({
  value,
  onChange,
  readOnly,
  label,
}: {
  value: string;
  onChange: (text: string) => void;
  readOnly: boolean;
  label: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const change = useRef(onChange);
  useEffect(() => {
    change.current = onChange;
  }, [onChange]);

  useEffect(() => {
    const v = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          json(),
          syntaxHighlighting(highlight),
          ruLinter,
          lintGutter(),
          theme,
          EditorView.lineWrapping,
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({ 'aria-label': label }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) change.current(u.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = v;
    return () => {
      v.destroy();
      view.current = null;
    };
    // Редактор создаётся один раз на файл и режим; текст снаружи приходит эффектом ниже.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, label]);

  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} data-testid="raw-editor" className="min-w-0" />;
}
