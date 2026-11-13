// «Уведомления и напоминания» (CC-0027): журнал (сверху новые, фильтр по виду и каналу, «показать
// все», ответы каналов доставки словами), напоминания (очередь, «показать все», «Отменить…» — план →
// «да», кто и откуда отменил, отказ «уже отправлено»), «поставить напоминание» (план → «да» → итог;
// отказы словами; «только смотреть»), проверка каналов (по полям `preview`; строки CLI — под
// «подробнее»).
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, notify } from '@/mocks/handlers';
import { CHECK_SKIPPED } from '@/mocks/notifyData';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { attemptsText, backendResult, untilText, whenText } from './format';

/** Видимый текст без «подробнее». */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

async function open() {
  const user = userEvent.setup();
  renderApp('/notifications');
  await screen.findAllByTestId('notify-event');
  await screen.findAllByTestId('notify-reminder');
  await screen.findByTestId('notify-check-preview');
  return user;
}

const posts = () => notify.state.calls.filter((c) => !c.startsWith('GET '));

describe('CC-0027: слова экрана «Уведомления и напоминания»', () => {
  it('время по Москве, «через …», попытки, ответы каналов', () => {
    expect(whenText('2026-10-12T18:00:00Z', '2026-10-12T15:40:00Z')).toBe('12 октября, 21:00');
    expect(whenText('2027-01-02T06:00:00Z', '2026-10-12T15:40:00Z')).toBe('2 января 2027, 09:00');
    expect(untilText('2026-10-12T18:00:00Z', '2026-10-12T15:40:00Z')).toBe('через 2 ч 20 мин');
    expect(untilText('2026-10-12T16:00:00Z', '2026-10-12T15:40:00Z')).toBe('через 20 мин');
    expect(untilText('2026-10-20T07:00:00Z', '2026-10-12T15:40:00Z')).toBe('через 8 дней');
    expect(attemptsText(2, 8)).toBe('2 из 8 попыток');
    expect(backendResult('ok').label).toBe('дошло');
    expect(backendResult('error: HTTP 502').tone).toBe('danger');
    expect(backendResult('skipped: no chat').label).toBe('пропущено');
  });
});

describe('CC-0027: экран «Уведомления и напоминания»', () => {
  it('журнал: сверху новые, последние 20 из 23, ответы каналов, пути — под «подробнее»', async () => {
    const user = await open();
    const journal = screen.getByTestId('notify-journal');
    const rows = within(journal).getAllByTestId('notify-event');
    expect(rows).toHaveLength(20);
    expect(rows[0]).toHaveTextContent('пробное сообщение фабрики');
    expect(rows[0]).toHaveTextContent('вся фабрика');
    expect(screen.getByTestId('notify-journal-count')).toHaveTextContent(
      'Показаны последние 20 из 23.',
    );
    const halted = rows.find((r) => r.dataset.kind === 'run_halted')!;
    expect(halted).toHaveTextContent('батч остановился');
    expect(halted).toHaveTextContent('ExampleTech');
    expect(
      within(halted)
        .getAllByTestId('notify-backend')
        .map((b) => b.textContent),
    ).toEqual(['Журнал:дошло', 'Telegram:ошибка']);
    const upload = rows.find((r) => r.dataset.kind === 'upload')!;
    expect(plainText(upload)).not.toContain('pipeline/');
    expect(upload).toHaveTextContent('pipeline/example-film');
    expect(plainText(journal)).not.toContain('sent.jsonl');

    await user.click(within(journal).getByTestId('notify-journal-all'));
    await waitFor(() => expect(within(journal).getAllByTestId('notify-event')).toHaveLength(23));
    expect(screen.getByTestId('notify-journal-count')).toHaveTextContent('Всего 23.');
  });

  it('журнал: фильтр по виду и каналу — запрос к API; пусто — словами', async () => {
    const user = await open();
    const journal = screen.getByTestId('notify-journal');
    await user.selectOptions(within(journal).getByTestId('notify-journal-kind'), 'run_halted');
    await waitFor(() => expect(within(journal).getAllByTestId('notify-event')).toHaveLength(1));
    expect(notify.state.calls).toContain('GET /api/notify/journal?limit=20&kind=run_halted');
    await user.selectOptions(within(journal).getByTestId('notify-journal-channel'), 'example-film');
    expect(await within(journal).findByText('Таких уведомлений нет')).toBeInTheDocument();
  });

  it('напоминания: очередь словами, попытки, «Отменить…» у ждущих; «показать все» — история', async () => {
    const user = await open();
    const box = screen.getByTestId('notify-reminders');
    const rows = within(box).getAllByTestId('notify-reminder');
    expect(rows.map((r) => r.dataset.status)).toEqual([
      'failed',
      'exhausted',
      'pending',
      'pending',
    ]);
    expect(rows[0]).toHaveTextContent('не дошло — будет ещё попытка');
    expect(within(rows[0]!).getByTestId('notify-reminder-tries')).toHaveTextContent(
      '2 из 8 попыток · не принял: Telegram',
    );
    expect(within(rows[2]!).getByTestId('notify-reminder-when')).toHaveTextContent(
      '12 октября, 21:00 МСК',
    );
    for (const r of rows)
      expect(within(r).getByTestId('notify-reminder-cancel-open')).not.toHaveAttribute(
        'aria-disabled',
      );
    expect(box).not.toHaveTextContent('следующей версии');
    expect(posts()).toEqual([]);
    expect(plainText(box)).not.toContain('reminders.jsonl');

    await user.click(within(box).getByTestId('notify-reminders-all'));
    await waitFor(() => expect(within(box).getAllByTestId('notify-reminder')).toHaveLength(6));
    const sent = within(box)
      .getAllByTestId('notify-reminder')
      .find((r) => r.dataset.status === 'sent')!;
    expect(sent).toHaveTextContent('отправлено');
    expect(within(sent).queryByTestId('notify-reminder-cancel-open')).toBeNull();
  });

  const row = (id: string) =>
    screen.getAllByTestId('notify-reminder').find((r) => r.dataset.id === id)!;

  it('отменить: план — что значит отмена; «да» — отменено из центра, вами', async () => {
    const user = await open();
    await user.click(within(row('R5')).getByTestId('notify-reminder-cancel-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('notify-cancel-text')).toHaveTextContent(
      'Принять ролики Reel до вечерней публикации',
    );
    expect(within(dialog).getByTestId('notify-cancel-means')).toHaveTextContent(
      'Напоминание не уйдёт',
    );
    expect(plainText(dialog)).not.toContain('R5');
    const yes = within(dialog).getByTestId('notify-reminder-cancel-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const done = await screen.findByTestId('notify-cancel-done');
    expect(done).toHaveTextContent('Напоминание отменено');
    expect(done).toHaveTextContent('Отменено из центра, вами');
    expect(notify.state.written).toEqual(['cancel R5']);
    await waitFor(() =>
      expect(screen.getAllByTestId('notify-reminder').map((r) => r.dataset.id)).not.toContain('R5'),
    );
    await user.click(screen.getByTestId('notify-reminders-all'));
    await waitFor(() => expect(row('R5')).toHaveAttribute('data-status', 'cancelled'));
    expect(within(row('R5')).getByTestId('notify-reminder-cancelled')).toHaveTextContent(
      'Отменено из центра, вами',
    );
  });

  it('отменить: пока думали, напоминание ушло — отказ словами, ничего не отменено', async () => {
    const user = await open();
    await user.click(within(row('R6')).getByTestId('notify-reminder-cancel-open'));
    const dialog = await screen.findByRole('alertdialog');
    const yes = within(dialog).getByTestId('notify-reminder-cancel-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    notify.state.next = 'sent_meanwhile';
    await user.click(yes);
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'not_cancellable');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent(
      'Отменять нечего — напоминание уже отправлено или отменено',
    );
    expect(notify.state.written).toEqual([]);
  });

  it('поставить: пустая форма — план не спрашиваем; план → «да» → итог, очередь перечитана', async () => {
    const user = await open();
    const box = screen.getByTestId('notify-new');
    expect(within(box).getByTestId('notify-new-open')).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(box).getByTestId('notify-new-at'), '21:30');
    await user.type(within(box).getByTestId('notify-new-text'), 'Позвонить   монтажёру');
    await user.click(within(box).getByTestId('notify-new-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('notify-plan-when')).toHaveTextContent(
      'Напомнит 12 октября, 21:30 МСК · через 2 ч 50 мин',
    );
    expect(within(dialog).getByTestId('notify-plan-text')).toHaveTextContent('Позвонить монтажёру');
    expect(dialog).toHaveTextContent('Поставит: вы');
    expect(notify.state.written).toEqual([]);
    const yes = within(dialog).getByTestId('notify-new-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const done = await screen.findByTestId('notify-reminder-done');
    expect(done).toHaveTextContent('Напоминание поставлено');
    expect(done).toHaveTextContent('Уйдёт 12 октября, 21:30 МСК: «Позвонить монтажёру».');
    expect(notify.state.written).toEqual(['R7']);
    await waitFor(() =>
      expect(screen.getAllByTestId('notify-reminder').map((r) => r.dataset.id)).toContain('R7'),
    );
    expect(within(box).getByTestId('notify-new-at')).toHaveValue('');
  });

  it('отказ «время не подходит» — словами, строка фабрики, «да» погашено', async () => {
    const user = await open();
    const box = screen.getByTestId('notify-new');
    await user.type(within(box).getByTestId('notify-new-at'), 'вечером');
    await user.type(within(box).getByTestId('notify-new-text'), 'что-то');
    await user.click(within(box).getByTestId('notify-new-open'));
    const dialog = await screen.findByRole('alertdialog');
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'bad_time');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent(
      'Время не подходит — напоминание не поставлено',
    );
    expect(within(refusal).getByTestId('write-refusal-message')).toHaveTextContent(
      'нужно «ЧЧ:ММ» или «ГГГГ-ММ-ДД ЧЧ:ММ» по Москве',
    );
    expect(within(dialog).getByTestId('notify-new-confirm')).toBeDisabled();
  });

  it('только смотреть — «Поставить…» погашено причиной, план не спрашиваем', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const user = await open();
    const box = screen.getByTestId('notify-new');
    await user.type(within(box).getByTestId('notify-new-at'), '21:30');
    await user.type(within(box).getByTestId('notify-new-text'), 'x');
    await waitFor(() =>
      expect(within(box).getByTestId('notify-new-open')).toHaveAttribute('data-writes', 'off'),
    );
    await user.click(within(box).getByTestId('notify-new-open'));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(posts()).toEqual([]);
  });

  it('проверка каналов: включены, что уходит с машины, по каналу — примет ли и что получит; строки — под «подробнее»', async () => {
    await open();
    const card = screen.getByTestId('notify-check');
    expect(within(card).getByTestId('notify-check-on')).toHaveTextContent(
      'Включены:ЖурналБаннер MacTelegram',
    );
    expect(within(card).getByTestId('notify-check-external')).toHaveTextContent(
      'С этой машины уходит: Telegram — текст уведомления получает внешний сервис.',
    );
    expect(within(card).getByTestId('notify-check-default')).toHaveTextContent(
      'По умолчанию — Журнал; остальные включены в настройках фабрики.',
    );
    const backends = within(card).getAllByTestId('notify-check-backend');
    expect(backends.map((b) => [b.dataset.name, b.dataset.ready])).toEqual([
      ['log', '1'],
      ['macos', '1'],
      ['telegram', '1'],
    ]);
    expect(backends[2]).toHaveTextContent('уходит с машины');
    expect(within(backends[2]!).getByTestId('notify-check-would-get')).toHaveTextContent(
      'проверка уведомлений фабрики',
    );
    const tgText = within(backends[2]!).getByTestId('notify-check-would-get');
    expect(tgText).toHaveTextContent('Фабрика · батч закончен');
    expect(tgText).toHaveTextContent('и ссылку на центр');
    expect(plainText(card)).not.toContain('run_done');
    expect(plainText(card)).not.toContain('пульт');
    expect(plainText(card)).not.toContain('127.0.0.1');
    expect(card).toHaveTextContent('http://127.0.0.1:8790/');
    expect(plainText(card)).not.toContain('would get');
    expect(plainText(card)).not.toContain('sent.jsonl');
    expect(card).toHaveTextContent('notify/sent.jsonl');
    expect(within(card).getByTestId('notify-check-sent')).toHaveTextContent('Ничего не отправлено');
  });

  it('проверка каналов: Telegram без адреса — «пропустит», почему — словами, настройка — под «подробнее»', async () => {
    notify.state.check = structuredClone(CHECK_SKIPPED);
    await open();
    const tg = screen
      .getAllByTestId('notify-check-backend')
      .find((b) => b.dataset.name === 'telegram')!;
    expect(tg).toHaveAttribute('data-ready', '0');
    expect(within(tg).getByTestId('notify-check-skip')).toHaveTextContent('не настроен');
    expect(plainText(tg)).not.toContain('NOTIFY_TELEGRAM_CHAT');
    expect(tg).toHaveTextContent('NOTIFY_TELEGRAM_CHAT');
  });

  it('чтения не прошли — словами фабрики, остальное на месте', async () => {
    notify.state.refuse.check = true;
    notify.state.refuse.reminders = true;
    renderApp('/notifications');
    await screen.findAllByTestId('notify-event');
    expect(await screen.findByText('Проверка каналов не прошла')).toBeInTheDocument();
    expect(await screen.findByText('Напоминания не прочитать')).toBeInTheDocument();
    expect(screen.getByTestId('notify-check')).toHaveTextContent(
      'Проверка уведомлений фабрики не прошла.',
    );
  });

  it('колокольчик в шапке ведёт на экран', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await user.click(screen.getByRole('link', { name: 'Уведомления и напоминания' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Уведомления и напоминания' }),
    ).toBeInTheDocument();
  });
});

describe('CC-0188: приёмка и «залито в Studio» в журнале', () => {
  it('новые виды словами; body — под свёрнутым «Подробнее», переносы как есть', async () => {
    await open();
    const journal = screen.getByTestId('notify-journal');
    const rows = within(journal).getAllByTestId('notify-event');
    const accepted = rows.find((r) => r.dataset.kind === 'accepted')!;
    const uploaded = rows.find((r) => r.dataset.kind === 'uploaded')!;
    expect(accepted).toHaveTextContent('Приёмка');
    expect(uploaded).toHaveTextContent('Залито в Studio');
    expect(uploaded).toHaveTextContent('выйдет 13 октября');
    expect(within(uploaded).queryByTestId('notify-event-body')).toBeNull();

    const body = within(accepted).getByTestId('notify-event-body');
    expect(body.closest('details')).not.toHaveAttribute('open');
    expect(body.closest('details')!.querySelector('summary')).toHaveTextContent(/^Подробнее/);
    expect(body.textContent).toContain('Принято: 2 из 3\n  • «Чип за 60 секунд»');
    expect(body).toHaveClass('whitespace-pre-wrap');
    expect(plainText(accepted)).not.toContain('Принято: 2 из 3');

    const upload = rows.find((r) => r.dataset.kind === 'upload')!;
    expect(
      within(upload)
        .getAllByTestId('notify-backend')
        .map((b) => b.textContent),
    ).toEqual(['Журнал:дошло']);
  });

  it('body — простым текстом: разметка не рендерится; не строка — ничего', async () => {
    notify.state.journal = [
      {
        at: '2026-10-12T10:00:00Z',
        kind: 'accepted',
        channel: null,
        key: 'a1',
        text: 'Приёмка',
        link: null,
        backends: { log: 'ok' },
        body: '*жирный*\n<b>тег</b>\n<img src=x onerror=alert(1)>',
      },
      {
        at: '2026-10-12T11:00:00Z',
        kind: 'uploaded',
        channel: null,
        key: 'u1',
        text: 'Залито',
        link: null,
        backends: { log: 'ok' },
        body: { lines: ['не строка'] },
      },
    ];
    await open();
    const rows = screen.getAllByTestId('notify-event');
    const accepted = rows.find((r) => r.dataset.kind === 'accepted')!;
    const body = within(accepted).getByTestId('notify-event-body');
    expect(body.textContent).toBe('*жирный*\n<b>тег</b>\n<img src=x onerror=alert(1)>');
    expect(body.querySelector('b, img, strong')).toBeNull();
    const uploaded = rows.find((r) => r.dataset.kind === 'uploaded')!;
    expect(within(uploaded).queryByTestId('notify-event-body')).toBeNull();
    expect(uploaded).toHaveTextContent('Залито в Studio');
  });
});
