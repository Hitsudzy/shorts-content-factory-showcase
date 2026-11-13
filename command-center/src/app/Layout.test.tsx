import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp } from '@/test/renderApp';

import { activeAreaPath, AREAS } from './areas';

const nav = () => screen.getByRole('navigation', { name: 'Разделы' });
/** Маршруты ленивые: сначала «Загружаю…», потом оболочка. */
const ready = () => screen.findByRole('navigation', { name: 'Разделы' });
const tab = (name: string) => within(nav()).getByRole('link', { name });
const current = () =>
  within(nav())
    .getAllByRole('link')
    .filter((l) => l.getAttribute('aria-current') === 'page');

describe('activeAreaPath — какой таб активен (CC-0085)', () => {
  it.each([
    ['/', ''],
    ['/?tour=1', ''],
    ['/channels', 'channels'],
    ['/channels/', 'channels'],
    ['/channels/reel', 'channels'],
    ['/channels/new', 'channels'],
    ['/questions?view=requests', 'questions'],
    ['/videos?batch=2026-10-12_reel', 'videos'],
    ['/videos/', 'videos'],
    ['/tokens#data', 'tokens'],
    ['/versions', 'versions'],
  ])('%s → %j', (path, area) => {
    expect(activeAreaPath(path)).toBe(area);
  });

  it('путь вне областей — ни один таб (и не Главная)', () => {
    expect(activeAreaPath('/nope')).toBeNull();
    expect(activeAreaPath('/channelsx')).toBeNull();
    expect(activeAreaPath('/x/channels')).toBeNull();
  });

  it('у каждой области есть путь, на котором активна она', () => {
    for (const a of AREAS) expect(activeAreaPath(`/${a.path}`)).toBe(a.path);
  });
});

describe('полоса табов и знак Example (CC-0085)', () => {
  it.each([
    ['/', 'Главная'],
    ['/channels/reel', 'Каналы'],
    ['/channels/new', 'Каналы'],
    ['/questions?view=requests', 'Вопросы'],
    ['/videos?batch=2026-10-12_reel', 'Ролики'],
  ])('на %s активен ровно один таб — «%s», с видом активного', async (path, name) => {
    renderApp(path);
    await ready();
    expect(current()).toEqual([tab(name)]);
    const cls = tab(name).className;
    expect(cls).toContain('border-primary-text');
    expect(cls).toContain('font-semibold');
    // Раньше Radix Slot склеивал функцию NavLink в строку — в классе был её исходный текст.
    expect(cls).not.toContain('=>');
    expect(cls).not.toContain('isActive');
    const other = tab(name === 'Главная' ? 'Батчи' : 'Главная');
    expect(other).not.toHaveAttribute('aria-current');
    expect(other.className).toContain('border-transparent');
    expect(other.className).not.toContain('font-semibold');
    // Ховер — только у неактивных, приглушённым тоном; переход гасится при reduced motion.
    expect(other.className).toContain('hover:text-foreground');
    expect(other.className).toContain('hover:border-muted-foreground/50');
    expect(other.className).toContain('motion-reduce:transition-none');
    expect(cls).not.toContain('hover:border');
  });

  it('путь вне областей — ни один таб не активен', async () => {
    renderApp('/nope');
    await ready();
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(current()).toEqual([]);
  });

  it('счётчик и точка отстоят от подписи через gap, без своих полей', async () => {
    renderApp('/');
    await ready();
    for (const a of AREAS) {
      const cls = tab(a.short).className;
      expect(cls).toContain('inline-flex');
      expect(cls).toContain('gap-1.5');
    }
    const badge = await within(tab('Вопросы')).findByText(/^\d+$/);
    expect(badge.className).not.toMatch(/\bm[lrx]-/);
  });

  it('знак Example — ссылка на главную, с понятным именем', async () => {
    renderApp('/batches');
    await ready();
    const logo = screen.getByRole('link', { name: 'На главную' });
    expect(logo).toHaveAttribute('href', '/');
    expect(logo).toHaveTextContent('Example');
    await userEvent.click(logo);
    expect(await screen.findByRole('heading', { name: 'Главная', level: 1 })).toBeInTheDocument();
    expect(current()).toEqual([tab('Главная')]);
  });
});
