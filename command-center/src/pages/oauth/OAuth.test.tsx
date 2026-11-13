// «Токены, OAuth и данные API» (CC-0029): токен без значения (состояние и срок словами, разрешения,
// файлы, команда входа с «Скопировать»), отзыв доступа (сухой прогон; «Отозвать доступ…» по
// `confirm_available` — план → «да» → итог: ответ Google, токен удалён, запись удаления), данные
// API по каналам, «Удалить по сроку…» (план → «да»), удаление plan → «да» (окно перечисляет по
// каналам, что удалится и что останется; отказы словами; «только смотреть»), точка у таба.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { byChannel, type ApiDataPlan } from '@/api/oauth';
import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, oauth } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { leftText, modeText, shareLines, termText } from './format';

/** Видимый текст без «подробнее». */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

const REFRESH = /refresh_token|ya29\.|1\/\/0/;

async function open() {
  const user = userEvent.setup();
  renderApp('/tokens');
  await screen.findByTestId('oauth-token-view');
  await screen.findByTestId('oauth-revoke-view');
  await screen.findByTestId('oauth-api-data-view');
  return user;
}

const posts = () => oauth.state.calls.filter((c) => !c.startsWith('GET '));

const PLAN: ApiDataPlan = {
  reason: 'x',
  channels: ['example-film', 'example-tech'],
  empty: false,
  files: ['analytics/example-film/daily.jsonl', 'analytics/example-tech/runs.jsonl'],
  dirs: ['analytics/example-film/summary'],
  rows: [
    {
      entry_id: 'e1',
      channel: 'example-tech',
      slug: 'chip',
      batch: null,
      publish_day: null,
      video_id: 'V1',
    },
  ],
  texts: [
    { file: 'publish/README.md', video_id: 'V1' },
    { file: 'publish/README.md', video_id: 'V9' },
  ],
  journal: 'publish/uploads.json',
  lines: ['  dir   analytics/example-film/summary/ (6 file(s))'],
};

describe('CC-0029: слова экрана «Токены, OAuth и данные API»', () => {
  it('срок, режим, план по каналам — без путей', () => {
    expect(leftText(96)).toBe('4 дня');
    expect(leftText(20.4)).toBe('20 ч');
    expect(leftText(0.5)).toBe('30 мин');
    expect(modeText('testing', 7)).toBe('тестовый режим Google — токен на 7\u00a0дней');
    expect(modeText('production', 7)).toBe('рабочий режим Google — без фиксированного срока');
    const shares = byChannel(PLAN);
    expect(shares.map((s) => s.channel)).toEqual(['example-film', 'example-tech', null]);
    expect(shareLines(shares[0]!, PLAN)).toEqual([
      'Статистика просмотров из YouTube Analytics: по дням',
      'Сводка аналитика по этой статистике (6\u00a0файлов)',
    ]);
    expect(shareLines(shares[1]!, PLAN)).toEqual([
      'Статистика просмотров из YouTube Analytics: журнал загрузок',
      'Данные, полученные через API YouTube, в 1\u00a0записи публикаций: «Chip» — остальное в записях остаётся',
      'Ссылки на ролики в 1\u00a0тексте заменятся пометкой',
    ]);
    expect(shares[2]!.texts).toEqual([{ file: 'publish/README.md', video_id: 'V9' }]);
  });
});

describe('CC-0029: экран «Токены, OAuth и данные API»', () => {
  it('токен: срок словами, разрешения, файлы, команда входа; строка фабрики — под «подробнее»', async () => {
    await open();
    const card = screen.getByTestId('oauth-token');
    expect(within(card).getByTestId('oauth-token-kind')).toHaveTextContent('действует');
    expect(within(card).getByTestId('oauth-token-term')).toHaveTextContent(
      'Действует ещё 4 дня — до 16 октября, 18:40 МСК',
    );
    expect(within(card).getByTestId('oauth-mode')).toHaveTextContent(
      'тестовый режим Google — токен на 7 дней',
    );
    expect(
      within(card)
        .getAllByTestId('oauth-scope')
        .map((s) => `${s.textContent}:${s.dataset.granted}`),
    ).toEqual(['Загрузка роликов:true', 'Чтение канала:true', 'Аналитика:true']);
    expect(within(card).getByTestId('oauth-files')).toHaveTextContent(
      'токен на местеклиент OAuth на местесостояние на месте',
    );
    expect(within(card).getByTestId('oauth-command')).toHaveTextContent(
      'agents/publisher/.venv/bin/python agents/publisher/upload.py --authorize',
    );
    expect(within(card).getByTestId('oauth-command-copy')).toBeInTheDocument();
    expect(plainText(card)).not.toContain('agents/publisher');
    expect(within(card).getByTestId('oauth-signin')).not.toHaveAttribute('data-urgent');
    expect(plainText(card)).not.toContain('ok   oauth');
    expect(card).toHaveTextContent('ok oauth: токен YouTube действует ещё 96 ч');
    expect(screen.queryByTestId('tab-token-mark')).toBeNull();
  });

  it('токен истёк, нет токена, не хватает разрешения — словами; точка у таба', async () => {
    oauth.state.token = 'expired';
    renderApp('/tokens');
    expect(await screen.findByTestId('oauth-token-term')).toHaveTextContent(
      'Истёк 11 октября, 12:00 МСК — загрузка и метрики стоят',
    );
    expect(screen.getByTestId('oauth-signin')).toHaveAttribute('data-urgent', '1');
    expect(screen.getByTestId('oauth-signin')).toHaveTextContent('Переразрешить доступ');
    const mark = await screen.findByTestId('tab-token-mark');
    expect(mark).toHaveAttribute('data-tone', 'danger');
    // CC-0085: отступ от подписи — gap таба, у точки своих полей нет.
    expect(mark.className).not.toMatch(/\bm[lrx]-/);
    expect(mark.parentElement!.className).toContain('gap-1.5');
  });

  it('нет токена — «Разрешить доступ», файлов нет; отзывать у Google нечего', async () => {
    oauth.state.token = 'no-auth';
    await open();
    expect(screen.getByTestId('oauth-token-kind')).toHaveTextContent('нет токена');
    expect(screen.getByTestId('oauth-signin')).toHaveTextContent('Разрешить доступ');
    expect(screen.getByTestId('oauth-files')).toHaveTextContent('токен нет');
    expect(screen.getAllByTestId('oauth-scope').map((s) => s.dataset.granted)).toEqual([
      'null',
      'null',
      'null',
    ]);
    expect(screen.getByTestId('oauth-revoke-steps')).toHaveTextContent(
      'Отзывать у Google нечего — токена нет',
    );
  });

  it('не хватает разрешения и скоро истечёт', () => {
    expect(
      termText({
        kind: 'no-scope',
        scopes: {
          required: [],
          granted: [],
          missing: ['https://www.googleapis.com/auth/yt-analytics.readonly'],
          short: {
            'https://www.googleapis.com/auth/yt-analytics.readonly': 'yt-analytics.readonly',
          },
        },
      } as never),
    ).toBe('У токена нет разрешения: Аналитика');
    expect(
      termText({
        kind: 'expires-soon',
        hours_left: 20,
        expires_at: '2026-10-13T11:40:00Z',
        now: '2026-10-12T15:40:00Z',
      } as never),
    ).toBe('Истекает через 20 ч — 13 октября, 14:40 МСК');
  });

  it('отзыв: что сделает — словами и по каналам; кнопка открыта, пока не нажали — ничего не уходит', async () => {
    await open();
    const card = screen.getByTestId('oauth-revoke');
    const steps = within(card).getByTestId('oauth-revoke-steps');
    expect(steps).toHaveTextContent('Google отзовёт разрешение фабрики');
    expect(steps).toHaveTextContent('Файл токена на этой машине удалится.');
    expect(steps).toHaveTextContent('Данные API удалятся: 11 объектов — 2 канала:');
    expect(within(card).getByTestId('oauth-revoke-button')).toHaveAttribute(
      'data-available',
      'true',
    );
    expect(within(card).getByTestId('oauth-revoke-open')).not.toHaveAttribute('aria-disabled');
    expect(card).not.toHaveTextContent('следующей версии');
    expect(posts()).toEqual([]);
    expect(plainText(card)).not.toContain('/home/');
    expect(card).toHaveTextContent('revoke - dry run (add --yes):');
    expect(within(card).getByTestId('oauth-google-page')).toHaveAttribute(
      'href',
      'https://myaccount.google.com/permissions',
    );
  });

  it('данные API: по каналам, авто-прогон без кнопки, ссылка на переключатель', async () => {
    await open();
    const card = screen.getByTestId('oauth-api-data');
    expect(within(card).getByTestId('oauth-api-data-kind')).toHaveTextContent('есть что обновить');
    expect(within(card).getByTestId('oauth-api-data-head')).toHaveTextContent('Отзыва доступа нет');
    expect(within(card).getByTestId('oauth-api-data-stale')).toHaveTextContent(
      'Не обновлялись 7+ дней: 1',
    );
    const held = within(within(card).getByTestId('oauth-held')).getAllByTestId('oauth-share');
    expect(held.map((s) => s.dataset.channel)).toEqual(['example-film', 'example-tech']);
    expect(held[0]).toHaveTextContent(
      'Статистика просмотров из YouTube Analytics: по дням, по окнам после публикации, журнал загрузок',
    );
    expect(held[0]).toHaveTextContent('Сводка аналитика по этой статистике (6 файлов)');
    expect(held[0]).toHaveTextContent(
      'Данные, полученные через API YouTube, в 2 записях публикаций: «Rink rivals», «Delver»',
    );
    expect(plainText(held[0]!)).not.toContain('rink-rivals');
    expect(held[0]).toHaveTextContent('rink-rivals');
    const due = within(card).getByTestId('oauth-due');
    expect(due).toHaveTextContent('Записи журнала, не обновлявшиеся 28+ дней:');
    expect(due).toHaveTextContent('delver');
    expect(within(due).getByTestId('oauth-auto-open')).not.toHaveAttribute('aria-disabled');
    expect(plainText(card)).not.toContain('analytics/');
    expect(within(card).getByRole('link', { name: '«Публикация»' })).toHaveAttribute(
      'href',
      '/publishing',
    );
  });

  it('удаление: план по каналам → «да» → итог; токен остаётся, данные перечитаны', async () => {
    const user = await open();
    const box = screen.getByTestId('oauth-purge');
    await user.click(within(box).getByTestId('oauth-purge-all'));
    expect(within(box).getByTestId('oauth-purge-open')).toHaveAttribute('aria-disabled', 'true');
    await user.click(within(box).getByTestId('oauth-purge-ch-example-tech'));
    await user.click(within(box).getByTestId('oauth-purge-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('oauth-purge-size')).toHaveTextContent(
      'Удалится 3 объекта — 1 канал:',
    );
    const shares = within(dialog).getAllByTestId('oauth-share');
    expect(shares.map((s) => s.dataset.channel)).toEqual(['example-tech']);
    expect(shares[0]).toHaveTextContent('«Quantum chip»');
    expect(plainText(shares[0]!)).not.toContain('quantum-chip');
    expect(within(dialog).getByTestId('oauth-purge-kept')).toHaveTextContent(
      'Токен YouTube — доступ не отзывается',
    );
    expect(within(dialog).getByTestId('oauth-purge-kept')).toHaveTextContent('Цифры из Studio');
    expect(dialog).toHaveTextContent('Удаляет: вы, из центра');
    expect(oauth.state.written).toEqual([]);
    const yes = within(dialog).getByTestId('oauth-purge-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const done = await screen.findByTestId('oauth-purge-done');
    expect(done).toHaveTextContent('Данные API удалены');
    expect(done).toHaveTextContent('Удалено 3 объекта: ExampleTech. Токен YouTube на месте');
    expect(oauth.state.written).toHaveLength(1);
    await waitFor(() =>
      expect(
        within(screen.getByTestId('oauth-held'))
          .getAllByTestId('oauth-share')
          .map((s) => s.dataset.channel),
      ).toEqual(['example-film']),
    );
    expect(posts()).toEqual([
      'POST /api/oauth/api-data/purge/plan',
      'POST /api/oauth/api-data/purge',
    ]);
  });

  it('отказ «да» — словами, строка фабрики; токен сгорел', async () => {
    const user = await open();
    oauth.state.next = 'factory_broken';
    await user.click(within(screen.getByTestId('oauth-purge')).getByTestId('oauth-purge-open'));
    const dialog = await screen.findByRole('alertdialog');
    const yes = within(dialog).getByTestId('oauth-purge-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'factory_broken');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent(
      'Фабрика ответила ошибкой — посмотрите состояние данных API',
    );
    expect(within(refusal).getByTestId('write-refusal-message')).toHaveTextContent(
      'посреди удаления',
    );
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('не выполнено');
    expect(within(dialog).getByTestId('oauth-purge-size')).toHaveTextContent(
      'Ничего не удалено. По плану удалилось бы 11 объектов',
    );
    expect(oauth.state.written).toEqual([]);
  });

  it('пусто — «Данных API нет», удалить нечего; только смотреть — погашено причиной', async () => {
    oauth.empty();
    oauth.state.token = 'no-auth';
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const user = await open();
    expect(screen.getByText('Данных API нет')).toBeInTheDocument();
    const steps = screen.getByTestId('oauth-revoke-steps');
    expect(steps).toHaveTextContent('Отзывать у Google нечего — токена нет.');
    expect(steps).not.toHaveTextContent('удалятся всё равно');
    expect(steps).toHaveTextContent('Данных API нет — удалять нечего.');
    expect(screen.getByTestId('oauth-due-none')).toHaveTextContent(
      'Авто-прогону сейчас удалять нечего.',
    );
    const btn = within(screen.getByTestId('oauth-purge')).getByTestId('oauth-purge-open');
    await waitFor(() => expect(btn).toHaveAttribute('data-writes', 'off'));
    await user.click(btn);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(posts()).toEqual([]);
  });

  it('отметка отзыва — когда удалится и предел; чтения не прошли — словами фабрики', async () => {
    oauth.markRevoked();
    oauth.state.refuse.revoke = true;
    renderApp('/tokens');
    expect(await screen.findByTestId('oauth-api-data-head')).toHaveTextContent(
      'Google отказал токену 10 октября — данные API удалятся 4 ноября, предел политики — 9 ноября',
    );
    expect(screen.getByTestId('oauth-api-data-kind')).toHaveTextContent('к удалению');
    expect(await screen.findByText('План отзыва не составлен')).toBeInTheDocument();
    expect(screen.getByTestId('oauth-revoke')).toHaveTextContent(
      'Фабрика ответила ошибкой: план отзыва не составлен.',
    );
  });
});

describe('CC-0087: отозвать доступ и удалить по сроку', () => {
  it('отозвать: план → «да» → итог: ответ Google, токен удалён, запись удаления; значения токена нет', async () => {
    const user = await open();
    const card = screen.getByTestId('oauth-revoke');
    await user.click(within(card).getByTestId('oauth-revoke-open'));
    const dialog = await screen.findByRole('alertdialog');
    const steps = await within(dialog).findByTestId('oauth-revoke-plan-steps');
    expect(steps).toHaveTextContent('Google отзовёт разрешение фабрики');
    const irreversible = within(dialog).getByTestId('oauth-revoke-irreversible');
    expect(irreversible).toHaveTextContent('Вернуть нельзя');
    // Предупреждение — раньше шагов: на телефоне его не закрывает липкий подвал.
    expect(
      irreversible.compareDocumentPosition(steps) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(plainText(dialog)).not.toContain('youtube.oauth-token');
    expect(oauth.state.written).toEqual([]);
    const yes = within(dialog).getByTestId('oauth-revoke-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const res = await screen.findByTestId('oauth-revoke-result');
    expect(res).toHaveAttribute('data-ok', '1');
    expect(within(res).getByTestId('oauth-revoke-google')).toHaveTextContent(
      'Google отозвал разрешение фабрики',
    );
    expect(within(res).getByTestId('oauth-revoke-token')).toHaveTextContent(
      'Файл токена на этой машине удалён.',
    );
    expect(within(res).getByTestId('oauth-revoke-deleted')).toHaveTextContent(
      'Запись в журнале удалений сделана: вы, из центра.',
    );
    expect(plainText(res)).not.toContain('api-data-deletions');
    expect(document.body.textContent).not.toMatch(REFRESH);
    // Окно закрылось — подсказка кнопки «Отозвать доступ…» не всплывает поверх итога.
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(oauth.state.written).toHaveLength(1);
  });

  it('Google не ответил — предупреждение: ничего не изменилось, токен на месте', async () => {
    oauth.state.googleAnswer = 'unreachable';
    const user = await open();
    await user.click(within(screen.getByTestId('oauth-revoke')).getByTestId('oauth-revoke-open'));
    const dialog = await screen.findByRole('alertdialog');
    const yes = within(dialog).getByTestId('oauth-revoke-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const res = await screen.findByTestId('oauth-revoke-result');
    expect(res).toHaveAttribute('data-ok', '0');
    expect(res).toHaveTextContent('Доступ не отозван — Google не ответил');
    expect(within(res).getByTestId('oauth-revoke-token')).toHaveTextContent('файл токена на месте');
    expect(plainText(res).match(/Google не ответил/g)).toHaveLength(1);
    expect(plainText(res)).not.toContain(' - ');
    expect(oauth.state.written).toEqual([]);
  });

  it('фабрика не отзывает из центра (confirm_available: false) — кнопка погашена причиной, план — с причиной', async () => {
    oauth.state.revokeOff = 'Отзыв из центра выключен на этой фабрике.';
    const user = await open();
    const card = screen.getByTestId('oauth-revoke');
    expect(within(card).getByTestId('oauth-revoke-button')).toHaveAttribute(
      'data-available',
      'false',
    );
    const btn = within(card).getByTestId('oauth-revoke-open');
    expect(btn).toHaveAttribute('aria-disabled', 'true');
    await user.click(btn);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(posts()).toEqual([]);
    const plan = oauth.revokePlan().body as { ok: boolean; why: string; confirm: string | null };
    expect(plan).toMatchObject({ ok: false, why: 'Отзыв из центра выключен на этой фабрике.' });
    expect(plan.confirm).toBeNull();
  });

  it('удалить по сроку: план — что подлежит; «да» — итог, запись удаления', async () => {
    const user = await open();
    const due = screen.getByTestId('oauth-due');
    await user.click(within(due).getByTestId('oauth-auto-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findAllByTestId('oauth-auto-plan-part')).toHaveLength(1);
    expect(dialog).toHaveTextContent('записи журнала, не обновлявшиеся 28+ дней');
    const yes = within(dialog).getByTestId('oauth-auto-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const done = await screen.findByTestId('oauth-auto-done');
    expect(done).toHaveTextContent('Удалено по сроку');
    expect(done).toHaveTextContent('вы, из центра');
    expect(oauth.state.written).toHaveLength(1);
    await waitFor(() =>
      expect(screen.getByTestId('oauth-due-none')).toHaveTextContent('удалять нечего'),
    );
    expect(within(screen.getByTestId('oauth-due')).getByTestId('oauth-auto-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });
});
