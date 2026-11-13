// CC-0062: «Да / Нет / Переделать» — подтверждение, слова с именем ролика как набраны, причина
// и код (из словаря или новый), отказы фабрики как есть, amend, очередь под батчем, только
// смотреть.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PAST } from '@/mocks/batches';
import { ACCEPT_BUILD_REFUSED } from '@/mocks/cards';
import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, videos } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { queuedBuildRefused } from '@/mocks/videos';
import { renderApp } from '@/test/renderApp';

const at = (slug: string) => `/videos?batch=${encodeURIComponent(PAST)}&v=${slug}`;

async function openVerdict(verdict: 'yes' | 'no' | 'redo') {
  const user = userEvent.setup();
  await user.click(await screen.findByTestId(`verdict-${verdict}`));
  const dialog = await screen.findByRole('alertdialog');
  return { user, dialog };
}

describe('CC-0062: приёмка ролика', () => {
  it('«Да»: слова с именем ролика заготовлены, уходят как набраны; «записано», список перечитан', async () => {
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('yes');
    const words = within(dialog).getByTestId('verdict-words');
    expect(words).toHaveValue('delver — ');
    await user.type(words, 'берём, хук держит ');
    expect(within(dialog).queryByTestId('verdict-reason')).toBeNull();
    expect(within(dialog).queryByTestId('verdict-amend')).toBeNull();
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    expect(await screen.findByTestId('acceptance-answer-text')).toHaveTextContent('Записано.');
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(videos.accepted).toEqual([
      {
        batch: PAST,
        slug: 'delver',
        body: {
          verdict: 'yes',
          words: 'delver — берём, хук держит ',
          reason: null,
          reason_code: null,
          amend: null,
        },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId('acceptance-verdict')).toHaveTextContent('принят'),
    );
    expect(screen.getByTestId('acceptance-answer')).toHaveTextContent(
      'коммит: Приёмка: delver принят (user (центр))',
    );
  });

  it('CC-0122: «Да» — куда лёг ролик: копилка канала; отказ копилки — словами фабрики и ссылкой', async () => {
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('yes');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    const queued = await screen.findByTestId('acceptance-answer-queued');
    expect(queued).toHaveAttribute('data-code', 'placed');
    expect(queued).toHaveTextContent('Копилка: ролик положен в копилку');
    // CC-0128: путь `publish/…/_queue/…mp4` — не на виду, строка фабрики целиком — под «Подробнее».
    expect(within(queued).getByTestId('acceptance-answer-queued-text')).toHaveTextContent(
      /^ролик положен в копилку$/,
    );
    expect(queued).not.toHaveTextContent('publish/');
    const raw = screen.getByTestId('acceptance-answer-queued-raw');
    expect(raw.closest('[data-slot="more"]')).not.toBeNull();
    expect(raw).toHaveTextContent(`publish/${PAST.split('/')[0]}/_queue/delver.mp4`);
    expect(within(queued).getByTestId('acceptance-answer-stash')).toHaveAttribute(
      'href',
      `/publishing?channel=${PAST.split('/')[0]}`,
    );
  });

  it('CC-0122: копилка отказала — строка фабрики и «Доложить в копилку» ссылкой, код — под «подробнее»', async () => {
    videos.setQueued({
      code: 'render_missing',
      text_ru: 'в копилку не положен: нет файла ролика в батче',
      publish_path: null,
      ok: false,
      skipped: false,
      refused: true,
      changed: false,
      left_out: false,
    });
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('yes');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    await waitFor(() =>
      expect(screen.getByTestId('acceptance-answer-queued')).toHaveAttribute(
        'data-code',
        'render_missing',
      ),
    );
    const refused = screen.getByTestId('acceptance-answer-queued');
    expect(refused).toHaveTextContent('Не в копилке: в копилку не положен: нет файла ролика');
    expect(within(refused).getByTestId('acceptance-answer-stash')).toHaveTextContent(
      'Доложить в копилку',
    );
    expect(refused).not.toHaveTextContent('render_missing');
  });

  it('CC-0175: автосборка карточки не запустилась — причина по-русски, коды под «подробнее»', async () => {
    videos.setQueued(queuedBuildRefused(PAST.split('/')[0]!, 'delver'));
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('yes');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    const queued = await screen.findByTestId('acceptance-answer-queued');
    const build = within(queued).getByTestId('accept-card-build');
    expect(build).toHaveAttribute('data-why', '1');
    const why = within(build).getByTestId('accept-card-build-why');
    expect(why).toHaveTextContent(
      'Карточку не собрать: модель не написала черновик карточки — ответ пустой; не прошла проверка утверждений.',
    );
    expect(why).not.toHaveTextContent('model_refused');
    const codes = within(build).getAllByTestId('accept-card-build-why-code');
    expect(codes.map((c) => c.dataset.code)).toEqual(['model_refused', 'claims_failed']);
    expect(codes[0]!.closest('[data-slot="more"]')).not.toBeNull();
    expect(codes[1]).toHaveTextContent('claims_failed: claim check failed');
  });

  it('CC-0175: why нет — строка автосборки как раньше, без «подробнее о сборке»', async () => {
    videos.setQueued({
      ...queuedBuildRefused(PAST.split('/')[0]!, 'delver'),
      card_build: { ...ACCEPT_BUILD_REFUSED, why: null },
    });
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('yes');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    const queued = await screen.findByTestId('acceptance-answer-queued');
    const build = within(queued).getByTestId('accept-card-build');
    expect(build).not.toHaveAttribute('data-why');
    expect(build).toHaveTextContent('Карточку не собрать: модель не написала черновик');
    expect(within(queued).queryByTestId('accept-card-build-why-code')).toBeNull();
  });

  it('«Нет» без причины — отказ фабрики как есть, код под «подробнее», окно открыто', async () => {
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('no');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    const refusal = await within(dialog).findByTestId('refusal-message');
    expect(refusal).toHaveTextContent(
      'Отказ без причины не записывается - нужна причина одной фразой.',
    );
    expect(within(dialog).getByText('код: rejection_without_reason')).toBeInTheDocument();
    expect(videos.accepted).toEqual([]);
  });

  it('«Нет» с новым кодом причины; словарь батча — в выборе', async () => {
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('no');
    const pick = within(dialog).getByTestId('verdict-code');
    expect(
      within(pick)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual([
      '— выберите код —',
      'weak_hook — хук скучный · 4',
      'off_topic — не по теме канала · 1',
      'новый код…',
    ]);
    await user.type(within(dialog).getByTestId('verdict-reason'), 'звук плывёт');
    await user.selectOptions(pick, 'новый код…');
    await user.type(within(dialog).getByTestId('verdict-new-code'), 'audio_drift');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    expect(await screen.findByTestId('acceptance-answer-text')).toHaveTextContent('Записано.');
    expect(videos.accepted[0]!.body).toMatchObject({
      verdict: 'no',
      reason: 'звук плывёт',
      reason_code: 'audio_drift',
    });
  });

  it('повторный вердикт: на verdict_already_given открывается «почему меняем», с ним — записано', async () => {
    renderApp(at('delver'));
    await screen.findByTestId('verdict-yes');
    // Вердикт дали из терминала — экран ещё не знает.
    videos.setAcceptance(PAST, 'delver', { verdict: 'accepted', answer: 'delver да' });
    const { user, dialog } = await openVerdict('redo');
    expect(within(dialog).queryByTestId('verdict-amend')).toBeNull();
    await user.type(within(dialog).getByTestId('verdict-reason'), 'хук слабый');
    await user.selectOptions(within(dialog).getByTestId('verdict-code'), 'weak_hook');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    expect(await within(dialog).findByTestId('refusal-message')).toHaveTextContent(
      'уже есть вердикт',
    );
    await user.type(within(dialog).getByTestId('verdict-amend'), 'пересмотрел');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    expect(await screen.findByTestId('acceptance-answer-redo')).toHaveTextContent(
      'Просьба записана, в очередь оператору ещё не поставлена.',
    );
    expect(videos.accepted[0]!.body).toMatchObject({ verdict: 'redo', amend: 'пересмотрел' });
  });

  it('под идущим батчем — «записано, ждёт конца батча» и почему', async () => {
    videos.setGoing([{ dir: 'pipeline/example-film/2026-10-10T0200Z', why: 'батч дня ещё идёт' }]);
    renderApp(at('delver'));
    const { user, dialog } = await openVerdict('yes');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    expect(await screen.findByTestId('acceptance-answer-text')).toHaveTextContent(
      'Записано, ждёт конца батча.',
    );
    expect(screen.getByTestId('acceptance-answer-batches')).toHaveTextContent('батч дня ещё идёт');
    expect(await screen.findByTestId('acceptance-pending')).toBeInTheDocument();
  });

  it('только смотреть: кнопки погашены с причиной, окно не открывается', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    renderApp(at('delver'));
    const yes = await screen.findByTestId('verdict-yes');
    await waitFor(() => expect(yes).toHaveAttribute('data-writes', 'off'));
    for (const v of ['yes', 'no', 'redo'])
      expect(screen.getByTestId(`verdict-${v}`)).toHaveAttribute('aria-disabled', 'true');
    await userEvent.setup().click(yes);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(videos.accepted).toEqual([]);
  });
});
