// Экраны во время загрузки (CC-0121): пока ответ задержан, на месте блока — скелетон (role=status,
// текст для читалки), после ответа — содержимое, скелетона больше нет.
import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { HISTORY_LIMIT } from '@/api/batches';
import { routeBatches } from '@/mocks/batches';
import { fixtures } from '@/mocks/fixtures';
import { batches } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

/** Задержка ответа до `release()`: тест сам решает, когда данные «приходят». */
function gate() {
  let release!: () => void;
  const wait = new Promise<void>((r) => (release = r));
  return { wait, release };
}

type Reply = { status: number; body: unknown } | null;

/**
 * Перехват GET: ждёт ворот, потом отвечает тем же подставным API, что и обычно (`route` —
 * маршрутизатор мока), либо готовым `body`.
 */
function held(path: string, g: { wait: Promise<void> }, answer: (url: URL) => Reply | object) {
  return http.get(`*${path}`, async ({ request }) => {
    await g.wait;
    const r = answer(new URL(request.url));
    if (r && 'status' in r && 'body' in r)
      return HttpResponse.json(r.body as object, { status: r.status });
    return HttpResponse.json(r as object);
  });
}

const skeletonIn = (el: HTMLElement) => el.querySelector('[data-slot="pending"]');

describe('скелетоны на экранах (CC-0121)', () => {
  it('главная: «Фабрика» и «Агенты» — скелетоны списка, пока версия не пришла', async () => {
    const g = gate();
    server.use(held('/api/version', g, () => fixtures.version));
    renderApp();
    const factory = await screen.findByTestId('factory-card');
    const agents = screen.getByTestId('agents-card');
    const sk = within(factory).getByRole('status');
    expect(sk).toHaveAttribute('aria-busy', 'true');
    expect(sk).toHaveAttribute('data-skeleton', 'list');
    expect(sk).toHaveTextContent('Спрашиваю фабрику о версии…');
    // три строки фактов: связь, рабочая копия, центр
    expect(sk.querySelectorAll(':scope > span.grid > span')).toHaveLength(3);
    expect(within(agents).getByRole('status')).toHaveTextContent('Загружаю пины агентов…');
    expect(within(factory).queryByRole('heading', { name: /^Версия/ })).toBeNull();

    g.release();
    expect(
      await within(factory).findByRole('heading', {
        name: `Версия ${fixtures.version.factory.version}`,
      }),
    ).toBeInTheDocument();
    await waitFor(() => expect(skeletonIn(factory)).toBeNull());
    expect(skeletonIn(agents)).toBeNull();
    expect(within(agents).getByText('footage-indexer')).toBeVisible();
  });

  it('батчи: «Прошлые прогоны» — страница строк скелетона, потом прогоны', async () => {
    const g = gate();
    // История задержана целиком; остальные чтения экрана — как обычно.
    server.use(held('/api/batches/history', g, (url) => routeBatches(batches, 'GET', url)));
    renderApp('/batches');
    const history = await screen.findByTestId('batch-history');
    const sk = within(history).getByRole('status');
    expect(sk).toHaveTextContent('Читаю историю…');
    expect(sk).toHaveAttribute('data-skeleton', 'rows');
    expect(sk.querySelectorAll(':scope > span:not(.sr-only)')).toHaveLength(HISTORY_LIMIT);
    expect(within(history).queryAllByTestId('run')).toHaveLength(0);

    g.release();
    await waitFor(() => expect(within(history).getAllByTestId('run').length).toBeGreaterThan(0));
    expect(skeletonIn(history)).toBeNull();
  });
});
