import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

import { parseInline, parseMarkdown, safeHref, splitIds, type ListItem } from './markdown';
import { MarkdownView } from './MarkdownView';

const md = (source: string) =>
  render(
    <RouterProvider
      router={createMemoryRouter([{ path: '*', element: <MarkdownView source={source} /> }])}
    />,
  );

describe('markdown тел задач: разбор', () => {
  it('строка: код, жирный, курсив, ссылка, номер задачи, голый адрес', () => {
    expect(
      parseInline('`a*b*` **жир** *кур* [дизайн](https://x.org/d) CF-0618 и https://y.org/p.'),
    ).toEqual([
      { t: 'code', v: 'a*b*' },
      { t: 'text', v: ' ' },
      { t: 'strong', c: [{ t: 'text', v: 'жир' }] },
      { t: 'text', v: ' ' },
      { t: 'em', c: [{ t: 'text', v: 'кур' }] },
      { t: 'text', v: ' ' },
      { t: 'link', href: 'https://x.org/d', c: [{ t: 'text', v: 'дизайн' }] },
      { t: 'text', v: ' ' },
      { t: 'task', id: 'CF-0618' },
      { t: 'text', v: ' и ' },
      { t: 'link', href: 'https://y.org/p', c: [{ t: 'text', v: 'https://y.org/p' }] },
      { t: 'text', v: '.' },
    ]);
  });

  it('snake_case и звёздочки в словах — не курсив', () => {
    expect(parseInline('CC_PASSWORD_HASH и 2*3*4')).toEqual([
      { t: 'text', v: 'CC_PASSWORD_HASH и 2*3*4' },
    ]);
  });

  it('блоки: заголовок, абзац, список, чеклист, нумерованный, код, цитата, таблица, черта', () => {
    const b = parseMarkdown(
      [
        '## Описание',
        'первая',
        'вторая',
        '',
        '- раз',
        '  - вложенный',
        '- [x] готово',
        '- [ ] нет',
        '',
        '3. три',
        '4. четыре',
        '```ts',
        '<b>код</b>',
        '```',
        '> цитата',
        '| a | b |',
        '|---|---|',
        '| 1 | CC-0124 |',
        '---',
      ].join('\n'),
    );
    expect(b.map((x) => x.t)).toEqual(['heading', 'p', 'ul', 'ol', 'code', 'quote', 'table', 'hr']);
    expect(b[1]).toEqual({ t: 'p', c: [{ t: 'text', v: 'первая вторая' }] });
    const ul = b[2] as { items: ListItem[] };
    expect(ul.items.map((i) => [i.depth, i.check])).toEqual([
      [0, null],
      [1, null],
      [0, true],
      [0, false],
    ]);
    expect(b[3]).toMatchObject({ t: 'ol', start: 3 });
    expect(b[4]).toEqual({ t: 'code', lang: 'ts', v: '<b>код</b>' });
  });

  it('безопасные ссылки — только http(s) и mailto', () => {
    expect(safeHref('https://x.org')).toBe('https://x.org');
    expect(safeHref('mailto:a@b.c')).toBe('mailto:a@b.c');
    expect(safeHref('javascript:alert(1)')).toBeNull();
    expect(safeHref('docs/design.md')).toBeNull();
    expect(parseInline('[жми](javascript:alert(1))')).toEqual([{ t: 'text', v: 'жми)' }]);
  });

  it('номера в подписи коммита', () => {
    expect(splitIds('WIP CC-0124: CF-0618 и всё')).toEqual([
      'WIP ',
      { id: 'CC-0124' },
      ': ',
      { id: 'CF-0618' },
      ' и всё',
    ]);
  });

  it('диапазон номеров — один кусок: CC-0001…0037, CF-0601–CF-0605, CC-0001...0037', () => {
    expect(parseInline('задачи CC-0001…0037 и CF-0618.')).toEqual([
      { t: 'text', v: 'задачи ' },
      { t: 'task', id: 'CC-0001', range: '…0037' },
      { t: 'text', v: ' и ' },
      { t: 'task', id: 'CF-0618' },
      { t: 'text', v: '.' },
    ]);
    expect(splitIds('CF-0601 – CF-0605, CC-0001...0037, CC-01245')).toEqual([
      { id: 'CF-0601', range: ' – CF-0605' },
      ', ',
      { id: 'CC-0001', range: '...0037' },
      ', CC-01245',
    ]);
  });
});

describe('markdown тел задач: вывод', () => {
  it('сырой HTML — текстом, без элементов; javascript: — не ссылка', () => {
    const { container } = md(
      '<script>alert(1)</script> <img src=x onerror=alert(1)> [жми](javascript:alert(1))',
    );
    expect(container.querySelector('script, img')).toBeNull();
    expect(screen.getByTestId('markdown')).toHaveTextContent('<script>alert(1)</script>');
    expect(container.querySelector('a')).toBeNull();
  });

  it('номера задач — ссылки на карточки, внешние ссылки — в новой вкладке', () => {
    md('Связано: CF-0626 и [дизайн](https://example.org/design)');
    const task = screen.getByRole('link', { name: 'CF-0626' });
    expect(task).toHaveAttribute('href', '/dev/CF-0626');
    const ext = screen.getByRole('link', { name: 'дизайн' });
    expect(ext).toHaveAttribute('target', '_blank');
    expect(ext).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('диапазон номеров не переносится на дефисе: ссылка и хвост в одном неразрывном куске', () => {
    md('Гриль: заведены CC-0001…0037.');
    const range = screen.getByTestId('task-range');
    expect(range).toHaveClass('whitespace-nowrap');
    expect(range).toHaveTextContent('CC-0001…0037');
    expect(screen.getByRole('link', { name: 'CC-0001' })).toHaveAttribute('href', '/dev/CC-0001');
  });

  it('чеклист — галочками, со словами для экранного диктора', () => {
    const { container } = md('- [x] готово\n- [ ] осталось');
    const items = container.querySelectorAll('li[data-check]');
    expect([...items].map((i) => i.getAttribute('data-check'))).toEqual(['done', 'open']);
    expect(items[0]).toHaveTextContent('сделано: готово');
    expect(items[1]).toHaveTextContent('не сделано: осталось');
  });
});
