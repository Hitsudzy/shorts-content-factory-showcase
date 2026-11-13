// CC-0025: экран «Мемы» — выбор банка, сетка и фильтры, просмотр, отметки кнопками и клавишами,
// «Сохранить отметки» с `base` (цепочкой), исчезнувшие мемы, «изменились в другом месте»,
// «Применить разбор» (план → «да»), только смотреть.
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { memes, mockGet } from '@/mocks/handlers';
import { TECH_BANK } from '@/mocks/memesData';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { resetMemeDrafts } from './draft';

afterEach(() => resetMemeDrafts());

/** Тела PUT отметок, ушедшие в подставной API. */
function spyPuts() {
  const puts: { decisions: Record<string, unknown>; base: string | null }[] = [];
  const nonGet: string[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method !== 'GET') nonGet.push(`${request.method} ${new URL(request.url).pathname}`);
    if (request.method === 'PUT')
      void request
        .clone()
        .json()
        .then((b) => puts.push(b as (typeof puts)[number]));
  });
  return { puts, nonGet };
}

describe('CC-0025: экран «Мемы»', () => {
  it('по умолчанию — банк, где больше всего ждут разбора; Reel и Science — один банк', async () => {
    renderApp('/memes');
    const picker = await screen.findByTestId('bank-picker');
    const options = within(picker).getAllByTestId('bank-option');
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent('ExampleFilm и ExampleScience');
    expect(options[0]).toHaveTextContent('Мемы в роликах включены');
    expect(options[1]).toHaveTextContent('ждут разбора: 35');
    expect(options[1]).toHaveTextContent(
      'Мемы в роликах выключены — включает фабрика после разбора',
    );
    expect(options[1]).toHaveAttribute('aria-pressed', 'true');
    const desk = await screen.findByTestId('meme-desk');
    expect(desk).toHaveAttribute('data-bank', TECH_BANK);
    expect(within(desk).getAllByTestId('meme')).toHaveLength(35);
    expect(within(desk).getByTestId('notice-stale')).toHaveTextContent(
      'Есть отметки мемов, которых в банке уже нет: 1',
    );
    expect(within(desk).getByTestId('notice-bands')).toHaveTextContent(
      'Grus plan — сверху белая полоса, 22% высоты',
    );
    await userEvent.click(options[0]!);
    expect(await screen.findByTestId('bank-shared')).toHaveTextContent(
      'Банк общий у ExampleFilm и ExampleScience',
    );
  });

  it('поиск и фильтры: по метке, по состоянию; «сбросить»', async () => {
    const user = userEvent.setup();
    renderApp('/memes?channel=example-tech');
    await screen.findAllByTestId('meme');
    await user.type(screen.getByTestId('meme-search'), 'coffee');
    expect(screen.getAllByTestId('meme').map((m) => m.dataset.id)).toEqual(['this-is-fine']);
    await user.clear(screen.getByTestId('meme-search'));
    await user.click(screen.getByTestId('filter-keep'));
    expect(screen.getAllByTestId('meme').map((m) => m.dataset.id)).toEqual(['always-has-been']);
    await user.click(screen.getByRole('button', { name: 'сбросить' }));
    expect(screen.getAllByTestId('meme')).toHaveLength(35);
    const tag = screen.getAllByTestId('tag-filter').find((t) => t.textContent === 'rebrand')!;
    await user.click(tag);
    expect(screen.getAllByTestId('meme').map((m) => m.dataset.id)).toEqual([
      'scooby-doo-mask-reveal',
      'theyre-the-same-picture',
    ]);
  });

  it('CC-0143: «Целиком» — обратное «С вырезкой», счёт с черновиком; включён один из двух', async () => {
    const user = userEvent.setup();
    renderApp('/memes?channel=example-tech&m=bell-curve');
    const viewer = await screen.findByTestId('meme-viewer');
    const cut = screen.getByTestId('filter-cut');
    const whole = screen.getByTestId('filter-whole');
    expect(cut).toHaveTextContent('С вырезкой · 3');
    expect(whole).toHaveTextContent('Целиком · 32');
    await user.click(whole);
    expect(whole).toHaveAttribute('aria-pressed', 'true');
    expect(cut).toHaveAttribute('aria-pressed', 'false');
    const ids = screen.getAllByTestId('meme').map((m) => m.dataset.id);
    expect(ids).toHaveLength(32);
    expect(ids).toContain('this-is-fine'); // GIF — всегда целиком
    for (const id of ['drake-hotline-bling', 'roll-safe', 'distracted-boyfriend'])
      expect(ids).not.toContain(id);
    // Отметка «можно вырезать» в черновике — мем уходит из «Целиком» в «С вырезкой».
    await user.click(within(viewer).getByTestId('mark-cut'));
    expect(whole).toHaveTextContent('Целиком · 31');
    expect(cut).toHaveTextContent('С вырезкой · 4');
    await user.click(cut);
    expect(cut).toHaveAttribute('aria-pressed', 'true');
    expect(whole).toHaveAttribute('aria-pressed', 'false');
  });

  it('просмотр: описание, метки, источник в новой вкладке, отказ вырезки; GIF не вырезать', async () => {
    const user = userEvent.setup();
    renderApp('/memes?channel=example-tech&m=distracted-boyfriend');
    const v = await screen.findByTestId('meme-viewer');
    expect(within(v).getByRole('heading', { name: 'Distracted boyfriend' })).toBeInTheDocument();
    expect(within(v).getByTestId('meme-source')).toHaveAttribute('target', '_blank');
    expect(within(v).getByTestId('cut-refused')).toHaveTextContent(
      'Вырезка не прошла проверку фабрики — мем пойдёт в ролик целиком.',
    );
    await user.click(within(v).getByTestId('meme-next'));
    await waitFor(() =>
      expect(screen.getByTestId('meme-viewer')).toHaveAttribute('data-id', 'drake-hotline-bling'),
    );
    expect(screen.getByTestId('meme-show-cut')).toBeInTheDocument();
  });

  it('GIF: вырезать нельзя, кусок видео — словами', async () => {
    renderApp('/memes?channel=example-tech&m=this-is-fine');
    const gif = await screen.findByTestId('meme-viewer');
    expect(within(gif).getByTestId('mark-cut')).toHaveAttribute('aria-disabled', 'true');
    expect(within(gif).getByText(/кусок видео 3–6,2 с/)).toBeInTheDocument();
  });

  it('отметки кнопками и клавишами — черновик; в фабрику — только по «Сохранить», с base цепочкой', async () => {
    const { puts, nonGet } = spyPuts();
    const user = userEvent.setup();
    renderApp('/memes?channel=example-tech&m=bell-curve');
    const v = await screen.findByTestId('meme-viewer');
    const base0 = memes.desk('example-tech').fingerprint;
    await user.click(within(v).getByTestId('mark-keep'));
    // K — оставить и к следующему, D — убрать, C — можно вырезать.
    fireEvent.keyDown(window, { key: 'k', code: 'KeyK' });
    await waitFor(() =>
      expect(screen.getByTestId('meme-viewer')).toHaveAttribute(
        'data-id',
        'bernie-once-again-asking',
      ),
    );
    fireEvent.keyDown(window, { key: 'c', code: 'KeyC' });
    fireEvent.keyDown(window, { key: 'd', code: 'KeyD' });
    await waitFor(() =>
      expect(screen.getByTestId('meme-viewer')).toHaveAttribute('data-id', 'buff-doge-vs-cheems'),
    );
    expect(screen.getByTestId('desk-unsaved')).toHaveTextContent('Не сохранено: 2 отметки');
    expect(nonGet).toEqual([]);

    await user.click(screen.getByTestId('desk-save'));
    await waitFor(() =>
      expect(screen.getByTestId('desk-unsaved')).toHaveTextContent('Все отметки сохранены'),
    );
    expect(puts).toHaveLength(1);
    expect(puts[0]!.base).toBe(base0);
    // Исчезнувший мем ушёл из тела, прежняя отметка осталась.
    expect(puts[0]!.decisions).toEqual({
      'always-has-been': { v: 'keep', cut: false },
      'bell-curve': { v: 'keep' },
      'bernie-once-again-asking': { cut: true, v: 'drop' },
    });
    const base1 = memes.desk('example-tech').fingerprint;
    expect(base1).not.toBe(base0);

    fireEvent.keyDown(window, { key: 'k', code: 'KeyK' });
    await user.click(await screen.findByTestId('desk-save'));
    await waitFor(() => expect(puts).toHaveLength(2));
    expect(puts[1]!.base).toBe(base1);
    expect(memes.desk('example-tech').decisions['buff-doge-vs-cheems']).toMatchObject({
      v: 'keep',
      marked_by: 'user',
      via: 'center',
    });
  });

  it('черновик поменяли мимо центра: check_changed — словами и «загрузить заново», без перезаписи', async () => {
    const user = userEvent.setup();
    renderApp('/memes?channel=example-tech&m=bell-curve');
    const v = await screen.findByTestId('meme-viewer');
    await user.click(within(v).getByTestId('mark-drop'));
    memes.editElsewhere(TECH_BANK, 'roll-safe', { v: 'keep' });
    await user.click(screen.getByTestId('desk-save'));
    const conflict = await screen.findByTestId('desk-conflict');
    expect(conflict).toHaveTextContent('Отметки изменились в другом месте');
    expect(memes.desk('example-tech').decisions['bell-curve']).toBeUndefined();
    expect(screen.getByTestId('desk-save')).toHaveAttribute('aria-disabled', 'true');
    await user.click(within(conflict).getByTestId('desk-reload'));
    await waitFor(() => expect(screen.queryByTestId('desk-conflict')).toBeNull());
    expect(screen.getByTestId('desk-unsaved')).toHaveTextContent('Все отметки сохранены');
    expect(screen.getByTestId('meme-viewer')).toHaveTextContent('Новый');
  });

  it('«Применить разбор»: с несохранённым погашен; план словами → «да» → стол перечитан', async () => {
    const user = userEvent.setup();
    renderApp('/memes?channel=example-tech&m=bell-curve');
    const v = await screen.findByTestId('meme-viewer');
    await user.click(within(v).getByTestId('mark-keep'));
    expect(screen.getByTestId('apply-open')).toHaveAttribute('aria-disabled', 'true');
    await user.click(screen.getByTestId('desk-save'));
    await waitFor(() =>
      expect(screen.getByTestId('apply-open')).not.toHaveAttribute('aria-disabled'),
    );
    await user.click(screen.getByTestId('apply-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('plan-accept')).toHaveTextContent(
      'Войдут в библиотеку: 2 мема',
    );
    expect(within(dialog).getByTestId('plan-accept')).toHaveTextContent('«Bell curve»');
    await user.click(within(dialog).getByTestId('apply-confirm'));
    expect(await screen.findByTestId('apply-done')).toHaveTextContent('Вошли в библиотеку: 2 мема');
    await waitFor(() =>
      expect(screen.getAllByTestId('meme').filter((m) => m.dataset.state === 'new')).toHaveLength(
        33,
      ),
    );
  });

  it('только смотреть: листать можно, отметки и сохранение погашены, клавиши молчат', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const { nonGet } = spyPuts();
    renderApp('/memes?channel=example-tech&m=bell-curve');
    const v = await screen.findByTestId('meme-viewer');
    await screen.findByTestId('desk-readonly');
    expect(within(v).getByTestId('mark-keep')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByTestId('apply-open')).toHaveAttribute('aria-disabled', 'true');
    fireEvent.keyDown(window, { key: 'k', code: 'KeyK' });
    expect(screen.getByTestId('meme-viewer')).toHaveAttribute('data-id', 'bell-curve');
    expect(screen.getByTestId('desk-unsaved')).toHaveTextContent('Все отметки сохранены');
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    await waitFor(() =>
      expect(screen.getByTestId('meme-viewer')).toHaveAttribute(
        'data-id',
        'bernie-once-again-asking',
      ),
    );
    expect(nonGet).toEqual([]);
  });

  it('банк не открывается — отказ фабрики словами', async () => {
    server.use(
      http.get('*/api/memes/example-tech', () =>
        HttpResponse.json(
          { code: 'bad_index', message: 'index.json банка не читается', details: ['x'] },
          { status: 409 },
        ),
      ),
    );
    renderApp('/memes?channel=example-tech');
    expect(await screen.findByText('Банк мемов не прочитать')).toBeInTheDocument();
    expect(screen.getAllByText('index.json банка не читается')[0]).toBeInTheDocument();
  });
});
