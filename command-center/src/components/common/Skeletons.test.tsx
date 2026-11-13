import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  Pending,
  PENDING_LABEL,
  SkeletonBadge,
  SkeletonCard,
  SkeletonFilmStrip,
  SkeletonPage,
  SkeletonRows,
  SkeletonTable,
  SkeletonText,
} from './Skeletons';

const bars = (el: Element) => el.querySelectorAll('[data-slot="skeleton"]');
const lines = (el: Element) => el.querySelectorAll<HTMLElement>(':scope > span:not(.sr-only)');

describe('скелетоны (CC-0121)', () => {
  it('обёртка — role=status, aria-busy и «Загружаю…» для читалки', () => {
    render(<Pending />);
    const s = screen.getByRole('status');
    expect(s).toHaveAttribute('aria-busy', 'true');
    expect(s).toHaveTextContent(PENDING_LABEL);
    expect(screen.getByText(PENDING_LABEL)).toHaveClass('sr-only');
  });

  it('свой текст для читалки, полоски от неё скрыты', () => {
    render(<SkeletonText lines={2} label="Читаю копилку…" />);
    const s = screen.getByRole('status');
    expect(s).toHaveTextContent('Читаю копилку…');
    const b = bars(s);
    expect(b).toHaveLength(2);
    b.forEach((x) => expect(x).toHaveAttribute('aria-hidden', 'true'));
  });

  it('полоски пульсируют, но не при prefers-reduced-motion; цвет — токен темы', () => {
    render(<SkeletonText />);
    const bar = bars(screen.getByRole('status'))[0]!;
    expect(bar).toHaveClass('animate-pulse');
    expect(bar).toHaveClass('motion-reduce:animate-none');
    expect(bar).toHaveClass('bg-skeleton');
  });

  it('строки текста — высотой строки 14/1.5 или заданной', () => {
    render(
      <>
        <SkeletonText lines={3} data-testid="a" />
        <SkeletonText lines={1} lineHeight={18} data-testid="b" />
      </>,
    );
    const a = lines(screen.getByTestId('a'));
    expect(a).toHaveLength(3);
    a.forEach((l) => expect(l.style.height).toBe('21px'));
    expect(lines(screen.getByTestId('b'))[0]!.style.height).toBe('18px');
  });

  it('карточка — рамка, шапка и строки', () => {
    render(<SkeletonCard rows={4} label="Читаю ленту…" data-testid="c" />);
    const c = screen.getByTestId('c');
    expect(c).toHaveAttribute('data-skeleton', 'card');
    expect(c.querySelector('.rounded-lg.border.bg-card')).not.toBeNull();
    // шапка — две полоски, строки — по одной
    expect(bars(c)).toHaveLength(2 + 4);
    render(<SkeletonCard rows={2} head={false} data-testid="nohead" />);
    expect(bars(screen.getByTestId('nohead'))).toHaveLength(2);
  });

  it('строки списка — заданной высоты и через заданный зазор', () => {
    render(<SkeletonRows rows={3} height={64} gap={10} data-testid="r" />);
    const r = screen.getByTestId('r');
    expect(r.style.gap).toBe('10px');
    const rows = lines(r);
    expect(rows).toHaveLength(3);
    rows.forEach((x) => {
      expect(x.style.height).toBe('64px');
      expect(x).toHaveClass('border');
    });
    render(<SkeletonRows rows={1} height={30} bordered={false} data-testid="flat" />);
    const flat = screen.getByTestId('flat');
    expect(lines(flat)[0]).not.toHaveClass('border');
    // низкая строка — одна полоска текста и значок
    expect(bars(flat)).toHaveLength(2);
  });

  it('таблица — заголовок и строки по колонкам', () => {
    render(<SkeletonTable rows={4} cols={5} data-testid="t" />);
    expect(bars(screen.getByTestId('t'))).toHaveLength((4 + 1) * 5);
    render(<SkeletonTable rows={2} cols={3} header={false} data-testid="t2" />);
    expect(bars(screen.getByTestId('t2'))).toHaveLength(2 * 3);
  });

  it('кинолента — столько кадров, сколько стадий, в рамке ленты', () => {
    render(<SkeletonFilmStrip frames={7} label="Читаю стадии…" />);
    const strip = screen.getByRole('status').querySelector<HTMLElement>('.film-strip')!;
    expect(strip.style.getPropertyValue('--film-cols')).toBe('repeat(7, minmax(0, 1fr))');
    expect(strip.querySelectorAll('.film-frame')).toHaveLength(7);
  });

  it('значок — строчный, с текстом для читалки', () => {
    render(
      <p>
        API <SkeletonBadge label="проверяю" width={60} />
      </p>,
    );
    const s = screen.getByRole('status');
    expect(s.tagName).toBe('SPAN');
    expect(s).toHaveTextContent('проверяю');
    expect((bars(s)[0] as HTMLElement).style.width).toBe('60%');
  });

  it('страница — один статус на всю заготовку', () => {
    render(<SkeletonPage />);
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByRole('status')).toHaveTextContent(PENDING_LABEL);
  });
});
