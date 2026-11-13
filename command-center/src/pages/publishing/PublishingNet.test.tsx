// «Публикация» (в), CC-0069: записи, что выходят за машину, — переключатель API-загрузки
// (заметка, предупреждения, фраза «аудит подтверждаю» набирается руками), загрузка на YouTube
// (сводка, условия, вопрос; «да» набирает человек; долгое ожидание; ошибки с «внести руками») и
// «загружено через Studio» (расхождения, would-add|exists). «Только смотреть» — всё погашено.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, publish } from '@/mocks/handlers';
import { PLACED, READY, REEL, SCIENCE, routePublish } from '@/mocks/publish';
import { AUDIT_PHRASE } from '@/mocks/publishWrites';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

/** День слота READY в ленте ExampleFilm (подставная «сегодня» — 10.10). */
const READY_DAY = '2026-10-13';
const PLACED_DAY = '2026-10-12';
const NOTE = 'аудит пройден 11.10 — письмо Google, решили на созвоне';

async function dialogOf(id: string) {
  const dialog = await screen.findByRole('alertdialog');
  const yes = within(dialog).getByTestId(`${id}-confirm`);
  return { dialog, yes };
}

function switchOn(channel = REEL) {
  publish.writes.state.switches[channel] = {
    on: true,
    at: '2026-10-09T10:00:00Z',
    by: 'user',
    note: 'включено (из центра)',
    history: [],
  };
}

async function openUpload(slug = READY, day = READY_DAY) {
  const user = userEvent.setup();
  renderApp(`/publishing?channel=${REEL}&slot=${day}/${slug}`);
  const card = await screen.findByTestId('upload-writes');
  await within(card).findByTestId('upload-open');
  return { user, card };
}

describe('CC-0069: переключатель API-загрузки', () => {
  it('включить: заметка → план с предупреждениями → фраза руками → включено', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const block = (await screen.findByTestId('channel-status')).querySelector(
      '[data-testid="state-api-upload"]',
    ) as HTMLElement;
    await user.click(await within(block).findByTestId('switch-on-toggle'));
    expect(within(block).getByTestId('switch-on-open')).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(block).getByTestId('switch-note'), NOTE);
    await user.click(within(block).getByTestId('switch-on-open'));
    const { dialog, yes } = await dialogOf('switch-on');
    expect(await within(dialog).findByTestId('switch-plan-warnings')).toHaveTextContent(
      'ещё не прошло аудит',
    );
    expect(within(dialog).getByTestId('switch-plan-note')).toHaveTextContent(`${NOTE} (из центра)`);
    const phrase = within(dialog).getByTestId('switch-audit');
    // фраза не подставлена: поле пустое, «да» погашено, пока не набрано
    expect(phrase).toHaveValue('');
    expect(within(dialog).getByTestId('switch-audit-field')).toHaveTextContent(AUDIT_PHRASE);
    expect(within(dialog).queryByRole('button', { name: /вставить/i })).not.toBeInTheDocument();
    // CC-0086: предложенное решение вопросов сюда не относится — ни плейсхолдера, ни «принять».
    expect(phrase).not.toHaveAttribute('placeholder');
    expect(
      within(dialog).queryByRole('button', { name: /принять предложение/i }),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(publish.writes.state.calls).toHaveLength(1));
    expect(yes).toBeDisabled();
    await user.type(phrase, AUDIT_PHRASE);
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(block).findByTestId('switch-done')).toHaveTextContent(
      'API-загрузка включена',
    );
    expect(publish.writes.state.calls.at(-1)!.body).toEqual({
      confirm: 'pub-api_upload_switch-1',
      audit: AUDIT_PHRASE,
    });
    await waitFor(() => expect(within(block).getByTestId('switch-off-toggle')).toBeInTheDocument());
  });

  it('фраза не та — audit_unconfirmed словами, токен сгорел, «Проверить заново»', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const status = await screen.findByTestId('channel-status');
    await user.click(await within(status).findByTestId('switch-on-toggle'));
    await user.type(within(status).getByTestId('switch-note'), NOTE);
    await user.click(within(status).getByTestId('switch-on-open'));
    const { dialog, yes } = await dialogOf('switch-on');
    await user.type(await within(dialog).findByTestId('switch-audit'), 'аудит');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveAttribute('data-code', 'audit_unconfirmed');
    expect(err).toHaveTextContent('Фраза аудита не совпала');
    expect(yes).toBeDisabled();
    expect(publish.writes.state.written).toEqual([]);
    await user.click(within(dialog).getByTestId('replan'));
    await waitFor(() =>
      expect(publish.writes.state.calls.filter((c) => c.kind === 'plan')).toHaveLength(2),
    );
  });

  it('выключить — без фразы', async () => {
    switchOn();
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const status = await screen.findByTestId('channel-status');
    await user.click(await within(status).findByTestId('switch-off-toggle'));
    await user.click(within(status).getByTestId('switch-off-open'));
    const { dialog, yes } = await dialogOf('switch-off');
    expect(await within(dialog).findByTestId('plan-head')).toHaveTextContent('можно выключить');
    expect(within(dialog).queryByTestId('switch-audit')).not.toBeInTheDocument();
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(status).findByTestId('switch-done')).toHaveTextContent('выключена');
    expect(publish.writes.state.calls.at(-1)!.body).toEqual({
      confirm: 'pub-api_upload_switch-1',
    });
  });

  it('канал-заглушка: план «включить нельзя» с причиной фабрики', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${SCIENCE}`);
    const status = await screen.findByTestId('channel-status');
    await user.click(await within(status).findByTestId('switch-on-toggle'));
    await user.type(within(status).getByTestId('switch-note'), NOTE);
    await user.click(within(status).getByTestId('switch-on-open'));
    const { dialog, yes } = await dialogOf('switch-on');
    expect(await within(dialog).findByTestId('plan-why')).toHaveTextContent('нечего грузить');
    expect(within(dialog).queryByTestId('switch-audit')).not.toBeInTheDocument();
    expect(yes).toBeDisabled();
  });
});

describe('CC-0069: загрузка на YouTube', () => {
  it('переключатель выключен — план отказывает строкой фабрики, токена и поля ответа нет', async () => {
    const { user, card } = await openUpload();
    expect(within(card).getByText('API-загрузка выключена')).toBeInTheDocument();
    await user.click(within(card).getByTestId('upload-open'));
    const { dialog, yes } = await dialogOf('upload');
    expect(await within(dialog).findByTestId('plan-why')).toHaveTextContent(
      'API-загрузка выключена',
    );
    expect(within(dialog).queryByTestId('upload-answer')).not.toBeInTheDocument();
    expect(yes).toBeDisabled();
  });

  it('сводка, условия, вопрос; «да» набирает человек; не «да» — токен цел; «да» — загружено', async () => {
    switchOn();
    const { user, card } = await openUpload();
    await user.click(within(card).getByTestId('upload-open'));
    const { dialog, yes } = await dialogOf('upload');
    expect(await within(dialog).findByTestId('upload-summary')).toHaveTextContent('Название:');
    expect(within(dialog).getByTestId('upload-tos')).toHaveTextContent('Условия использования');
    const answer = within(dialog).getByTestId('upload-answer');
    expect(within(dialog).getByTestId('upload-answer-field')).toHaveTextContent('Введите «да»');
    expect(answer).toHaveValue('');
    expect(within(dialog).queryByRole('button', { name: /вставить/i })).not.toBeInTheDocument();
    // CC-0086: «да» не подставляется и не подсказывается плейсхолдером, «принять» здесь нет.
    expect(answer).not.toHaveAttribute('placeholder');
    expect(
      within(dialog).queryByRole('button', { name: /принять предложение/i }),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(publish.writes.state.calls).toHaveLength(1));
    expect(yes).toBeDisabled();
    await user.type(answer, 'ок');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveAttribute('data-code', 'answer_required');
    expect(within(dialog).getByTestId('busy-note')).toHaveTextContent('впишите «да»');
    await user.clear(answer);
    await user.type(answer, 'да');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(card).findByTestId('upload-done')).toHaveTextContent(
      'Загружено на YouTube',
    );
    const confirms = publish.writes.state.calls.filter((c) => c.kind === 'confirm');
    expect(confirms.map((c) => c.body)).toEqual([
      { confirm: 'pub-api_upload-1', answer: 'ок' },
      { confirm: 'pub-api_upload-1', answer: 'да' },
    ]);
  });

  it('загрузка идёт долго: окно ждёт с отсчётом, «да» и «Отмена» погашены', async () => {
    switchOn();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    server.use(
      http.post('*/api/publish/:channel/upload', async ({ request }) => {
        const body: unknown = await request.json();
        await gate;
        const reply = routePublish(publish, 'POST', new URL(request.url), body)!;
        return HttpResponse.json(reply.body as object, { status: reply.status });
      }),
    );
    const { user, card } = await openUpload();
    await user.click(within(card).getByTestId('upload-open'));
    const { dialog, yes } = await dialogOf('upload');
    await user.type(await within(dialog).findByTestId('upload-answer'), 'да');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(dialog).findByTestId('act-waiting')).toHaveTextContent(
      'может занять несколько минут',
    );
    expect(within(dialog).getByTestId('elapsed')).toHaveTextContent(/0:0\d/);
    expect(yes).toBeDisabled();
    expect(yes).toHaveTextContent('Загружаю…');
    expect(within(dialog).getByRole('button', { name: 'Отмена' })).toBeDisabled();
    await user.click(yes);
    expect(publish.writes.state.calls.filter((c) => c.kind === 'confirm')).toHaveLength(0);
    release();
    expect(await within(card).findByTestId('upload-done')).toBeInTheDocument();
    expect(publish.writes.state.calls.filter((c) => c.kind === 'confirm')).toHaveLength(1);
  });

  it('загружено, но не записано — строки «внести руками» с «скопировать»', async () => {
    switchOn();
    publish.writes.state.uploadNext = 'uploaded_unrecorded';
    const { user, card } = await openUpload();
    await user.click(within(card).getByTestId('upload-open'));
    const { dialog, yes } = await dialogOf('upload');
    await user.type(await within(dialog).findByTestId('upload-answer'), 'да');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const manual = await within(dialog).findByTestId('upload-manual');
    expect(manual).toHaveTextContent('не загружайте его ещё раз');
    const lines = within(manual).getAllByTestId('upload-manual-line');
    expect(lines.some((l) => l.textContent?.includes('MANUAL publish/uploads.json'))).toBe(true);
    expect(within(manual).getAllByTestId('upload-manual-copy')).toHaveLength(lines.length);
    expect(within(dialog).getByTestId('write-refusal-title')).toHaveTextContent(
      'внесите её руками',
    );
  });

  it('токен YouTube надо переразрешить — словами, команда под «подробнее»', async () => {
    switchOn();
    publish.writes.state.uploadNext = 'reauthorize';
    const { user, card } = await openUpload();
    await user.click(within(card).getByTestId('upload-open'));
    const { dialog, yes } = await dialogOf('upload');
    await user.type(await within(dialog).findByTestId('upload-answer'), 'да');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(dialog).findByTestId('upload-reauthorize')).toHaveTextContent(
      'Переразрешите доступ',
    );
    expect(within(dialog).getByTestId('act-error')).toHaveAttribute('data-code', 'reauthorize');
  });

  it('«только смотреть»: «Загрузить» погашено, ни одного POST', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const { user, card } = await openUpload();
    const go = within(card).getByTestId('upload-open');
    await waitFor(() => expect(go).toHaveAttribute('data-writes', 'off'));
    await user.click(go);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(publish.writes.state.calls).toEqual([]);
  });
});

describe('CC-0069: «загружено через Studio»', () => {
  const readOf = (slug: string) => {
    const note = [...publish.state.notes.values()].find((n) => n.slug === slug)!;
    const f = note.studio!;
    return {
      title: f.title,
      description: f.description,
      tags: f.tags,
      visibility: 'Запланировано',
      publish_at: (f.schedule as { publish_at: string }).publish_at,
    };
  };

  it('поля не те — план показывает расхождения, «да» погашено', async () => {
    const { user, card } = await openUpload();
    await user.click(within(card).getByTestId('studio-record-toggle'));
    const go = within(card).getByTestId('studio-record-open');
    expect(go).toHaveAttribute('aria-disabled', 'true');
    await user.type(
      within(card).getByTestId('record-video'),
      'https://youtube.com/shorts/Ab3dE5gH7jK',
    );
    await user.type(within(card).getByTestId('record-title'), 'Vanguards: Doomsday Moved Again');
    await user.type(within(card).getByTestId('record-tags'), 'Zenith, MCU');
    await user.type(within(card).getByTestId('record-visibility'), 'Запланировано');
    await user.type(within(card).getByTestId('record-publish-at'), '2026-10-13T02:00+03:00');
    await user.click(within(card).getByTestId('studio-record-open'));
    const { dialog, yes } = await dialogOf('studio-record');
    const mism = await within(dialog).findByTestId('record-mismatches');
    expect(
      within(mism)
        .getAllByTestId('record-mismatch')
        .map((m) => m.dataset.field),
    ).toEqual(['title', 'description', 'tags', 'publish_at']);
    expect(within(mism).getAllByTestId('record-mismatch')[0]).toHaveTextContent('Название');
    expect(yes).toBeDisabled();
    expect(publish.writes.state.calls[0]!.body).toMatchObject({
      slug: READY,
      day: READY_DAY,
      video_id: 'Ab3dE5gH7jK',
    });
  });

  it('JSON из Studio совпал — «добавит запись» → записано, серия выросла', async () => {
    const { user, card } = await openUpload();
    await user.click(within(card).getByTestId('studio-record-toggle'));
    await user.type(within(card).getByTestId('record-video'), 'Ab3dE5gH7jK');
    await user.click(within(card).getByTestId('record-json'));
    await user.paste(JSON.stringify(readOf(READY)));
    await user.click(within(card).getByTestId('studio-record-open'));
    const { dialog, yes } = await dialogOf('studio-record');
    expect(await within(dialog).findByTestId('record-status')).toHaveTextContent('добавит запись');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(card).findByTestId('record-done')).toHaveTextContent(
      'Подряд без правок: 3 из 5',
    );
    await waitFor(() => expect(screen.getByTestId('state-studio')).toHaveTextContent('3 из 5'));
  });

  it('уже в журнале — «уже в журнале», записывать нечего', async () => {
    const { user, card } = await openUpload(PLACED, PLACED_DAY);
    await user.click(within(card).getByTestId('studio-record-toggle'));
    await user.type(within(card).getByTestId('record-video'), 'rJSXkLVswSs');
    await user.click(within(card).getByTestId('record-json'));
    await user.paste(JSON.stringify(readOf(PLACED)));
    await user.click(within(card).getByTestId('studio-record-open'));
    const { dialog, yes } = await dialogOf('studio-record');
    expect(await within(dialog).findByTestId('record-status')).toHaveTextContent('уже в журнале');
    expect(within(dialog).getByTestId('plan-why')).toHaveTextContent('записывать нечего');
    expect(yes).toBeDisabled();
  });

  it('JSON не читается — поле помечено, кнопка погашена с причиной', async () => {
    const { user, card } = await openUpload();
    await user.click(within(card).getByTestId('studio-record-toggle'));
    await user.type(within(card).getByTestId('record-video'), 'Ab3dE5gH7jK');
    await user.click(within(card).getByTestId('record-json'));
    await user.paste('{oops');
    expect(within(card).getByTestId('record-json')).toHaveAttribute('aria-invalid', 'true');
    expect(within(card).getByTestId('studio-record-open')).toHaveAttribute('aria-disabled', 'true');
  });
});
