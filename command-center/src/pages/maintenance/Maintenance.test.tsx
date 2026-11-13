// «Обслуживание и расход» (CC-0033): расход батча словами (без id батчей и команд на виду),
// батч без учёта расхода, сравнение прогонов, пул с правилом давности, записи plan → «да»
// (поле «да» пустое, кнопка — только после «да»), отказ «идёт батч», устаревший план, диск
// архива не подключён, только смотреть, скелетоны.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http } from 'msw';

import { fixtures } from '@/mocks/fixtures';
import { maintenance, mockGet } from '@/mocks/handlers';
import { REEL_HAND, TECH_EXEC } from '@/mocks/maintenanceData';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { bytesText, defectText, monthText, tokensText, variantText } from './format';

/** Видимый текст без «подробнее». */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

const RAW =
  /\d{4}-\d\d-\d\dT\d{4}Z|scripts\/|pipeline\/|shared\/|yt-[A-Za-z0-9]{6}|example(reel|tech|science)\b/;

async function open() {
  const user = userEvent.setup();
  renderApp('/maintenance');
  await screen.findByTestId('usage-view');
  await screen.findByTestId('pool-view');
  await screen.findByTestId('archive-view');
  return user;
}

async function openDialog(user: ReturnType<typeof userEvent.setup>, id: string) {
  await user.click(screen.getByTestId(`${id}-open`));
  return screen.findByRole('alertdialog');
}

describe('слова экрана', () => {
  it('токены, байты, месяцы, правила пула и расхождения — по-русски', () => {
    expect(tokensText(4_215_000)).toBe('4,2 млн');
    expect(tokensText(82_400)).toBe('82 тыс.');
    expect(bytesText(1.42 * 1024 ** 3)).toBe('1,4\u00a0ГБ');
    expect(bytesText(640 * 1024 ** 2)).toBe('640\u00a0МБ');
    expect(monthText('2026-09')).toBe('сентябрь 2026');
    expect(variantText('no_video older than 14 d')).toBe('Темы без ролика старше 14 дней');
    expect(defectText('stage video-editor: ran by hand, not by the executor')).toMatch(
      /^Стадия «.+» прошла вручную/,
    );
    expect(defectText('file 05_videos.json: executor only')).toBe(
      'Файл результата есть только у исполнителя',
    );
  });
});

describe('экран «Обслуживание и расход»', () => {
  it('расход батча: токены словами, стадии по убыванию, денег нет — сказано; id и команды — под «Подробнее»', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Обслуживание и расход');
    expect(screen.getByTestId('usage-batch')).toHaveDisplayValue('ExampleFilm · батч 09.10, 05:15');
    expect(screen.getByTestId('usage-total')).toHaveTextContent('млн');
    expect(screen.getByTestId('usage-money')).toHaveTextContent('Деньги: фабрика их не считает');
    const stages = screen.getAllByTestId('usage-stage');
    expect(stages.length).toBe(7);
    expect(stages[0]).toHaveTextContent('Opus');
    expect(plainText(document.querySelector('main')!)).not.toMatch(RAW);
    expect(screen.queryByText(/Скоро · версия/)).toBeNull();
  });

  it('батч до учёта расхода — «ещё не посчитан», подсказка фабрики — под «Подробнее»', async () => {
    const user = await open();
    await user.selectOptions(screen.getByTestId('usage-batch'), REEL_HAND);
    const none = await screen.findByTestId('usage-none');
    expect(none).toHaveTextContent('Расход этого батча ещё не посчитан');
    expect(plainText(none)).not.toMatch(/usage_from_transcripts/);
  });

  it('отказ расхода — словами фабрики и «Повторить»', async () => {
    maintenance.state.refuse.usage = true;
    renderApp('/maintenance');
    const card = await screen.findByTestId('usage');
    expect(await within(card).findByRole('alert')).toHaveTextContent('Расход не прочитан');
    expect(within(card).getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('сравнение: вручную против исполнителя — «ход прогона одинаков», с Tech — расхождения словами', async () => {
    const user = await open();
    expect(screen.getByTestId('compare-hint')).toBeInTheDocument();
    await user.click(screen.getByTestId('compare-run'));
    const same = await screen.findByTestId('compare-view');
    expect(same).toHaveAttribute('data-same', '1');
    expect(same).toHaveTextContent('ход прогона одинаков');
    await user.selectOptions(screen.getByTestId('compare-executor'), TECH_EXEC);
    await user.click(screen.getByTestId('compare-run'));
    await waitFor(() =>
      expect(screen.getByTestId('compare-view')).toHaveAttribute('data-same', '0'),
    );
    const defects = screen.getByTestId('compare-defects');
    expect(defects).toHaveTextContent('прошла вручную, у исполнителя её не было');
    expect(plainText(screen.getByTestId('compare'))).not.toMatch(RAW);
    // Один и тот же батч — кнопка погашена.
    await user.selectOptions(screen.getByTestId('compare-executor'), REEL_HAND);
    expect(screen.getByTestId('compare-run')).toBeDisabled();
  });

  it('пул: плитки, почему остаются; правило давности добавляет давнюю тему', async () => {
    const user = await open();
    expect(screen.getByTestId('pool-release')).toHaveTextContent('3 источника');
    expect(screen.getByTestId('pool-keep-why')).toHaveTextContent(
      'ролик принят, ещё не опубликован',
    );
    await user.click(screen.getByTestId('pool-stale'));
    await waitFor(() =>
      expect(screen.getByTestId('pool-release')).toHaveTextContent('4 источника'),
    );
    expect(plainText(screen.getByTestId('pool'))).not.toMatch(RAW);
    expect(screen.getByTestId('pool')).toHaveTextContent('Без хозяина');
  });

  it('пул: план → поле «да» пустое → «да» → освобождён; записано вами из центра', async () => {
    const user = await open();
    const dialog = await openDialog(user, 'pool-release');
    expect(await within(dialog).findByTestId('pool-plan-total')).toHaveTextContent(
      'Уйдёт 3 источника',
    );
    expect(within(dialog).getByTestId('pool-irreversible')).toHaveTextContent('Вернуть нельзя');
    // CC-0131: отсчёт на кнопке «да» — с пояснением, чей он.
    expect(within(dialog).getByTestId('pool-release-plan-life')).toHaveTextContent(
      /^План действует ещё \d+:\d\d — тот же отсчёт на кнопке/,
    );
    const yes = within(dialog).getByTestId('pool-yes');
    expect(yes).toHaveValue('');
    const confirm = within(dialog).getByTestId('pool-release-confirm');
    expect(confirm).toBeDisabled();
    await user.type(yes, 'нет');
    expect(confirm).toBeDisabled();
    await user.clear(yes);
    await user.type(yes, 'да');
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(maintenance.state.written.released).toEqual([]);
    await user.click(confirm);
    const done = await screen.findByTestId('pool-done');
    expect(done).toHaveTextContent('Удалено 3 источника');
    expect(maintenance.state.written.released).toHaveLength(3);
    await waitFor(() =>
      expect(screen.getByTestId('pool-release')).toHaveTextContent('0 источников'),
    );
    expect(screen.getByTestId('pool-release-open')).toHaveAttribute('aria-disabled', 'true');
  });

  it('журналы: батч начался после плана — отказ «идёт батч» словами, ничего не тронуто', async () => {
    const user = await open();
    const dialog = await openDialog(user, 'journals');
    expect(await within(dialog).findByTestId('journals-plan-total')).toHaveTextContent('3 журнала');
    expect(plainText(within(dialog).getByTestId('journals-plan-rows'))).toContain(
      'ExampleScience · батч 08.10, 06:00',
    );
    maintenance.state.openBatches = ['example-science/2026-10-14T0300Z'];
    await user.type(within(dialog).getByTestId('journals-yes'), 'да');
    await user.click(within(dialog).getByTestId('journals-confirm'));
    const refusal = await within(dialog).findByTestId('act-error');
    expect(refusal).toHaveAttribute('data-code', 'batch_open');
    expect(refusal).toHaveTextContent('Идёт батч — уборки и архив ждут, пока он закончится');
    expect(refusal).toHaveTextContent('ExampleScience · батч 14.10, 06:00');
    expect(plainText(refusal)).not.toMatch(RAW);
    expect(maintenance.state.written.journals).toBe(0);
  });

  it('журналы: идёт батч — план без подтверждения и причина; полоса «идёт батч» над пулом', async () => {
    maintenance.state.openBatches = ['example-science/2026-10-14T0300Z'];
    const user = await open();
    expect(screen.getByTestId('pool-going')).toHaveTextContent(
      'ExampleScience · батч 14.10, 06:00',
    );
    const dialog = await openDialog(user, 'journals');
    expect(await within(dialog).findByTestId('plan-why')).toHaveTextContent(
      'Открыт батч (ExampleScience · батч 14.10, 06:00) — запись подождёт',
    );
    expect(within(dialog).queryByTestId('journals-yes')).toBeNull();
    expect(within(dialog).getByTestId('journals-confirm')).toBeDisabled();
  });

  it('архив: план устарел — фабрика переплан делает сама, «да» снова пустое; потом — в архиве', async () => {
    const user = await open();
    const dialog = await openDialog(user, 'archive');
    const jobs = await within(dialog).findByTestId('archive-plan-jobs');
    expect(jobs).toHaveTextContent('ExampleFilm · сентябрь 2026');
    expect(jobs).toHaveTextContent('допишутся в архив месяца');
    expect(within(dialog).getByTestId('archive-space')).toHaveTextContent('свободно');
    maintenance.expireTokens();
    await user.type(within(dialog).getByTestId('archive-yes'), 'да');
    await user.click(within(dialog).getByTestId('archive-confirm'));
    const again = await within(dialog).findByTestId('replanned');
    expect(again).toHaveAttribute('data-code', 'confirm_expired');
    expect(again).toHaveTextContent('План устарел');
    await waitFor(() => expect(within(dialog).getByTestId('archive-yes')).toHaveValue(''));
    expect(within(dialog).getByTestId('archive-confirm')).toBeDisabled();
    await user.type(within(dialog).getByTestId('archive-yes'), 'да');
    await user.click(within(dialog).getByTestId('archive-confirm'));
    const done = await screen.findByTestId('archive-done');
    expect(done).toHaveTextContent('Месяц в архиве');
    expect(within(done).getByTestId('archive-done-commit')).toHaveTextContent('Коммит сделан');
    expect(maintenance.state.written.archived).toHaveLength(3);
  });

  it('архив: диск не подключён — проверка не прошла, план без подтверждения', async () => {
    maintenance.state.volumeMissing = true;
    const user = await open();
    expect(screen.getByTestId('archive-status')).toHaveTextContent('проверка не прошла');
    const dialog = await openDialog(user, 'archive');
    expect(await within(dialog).findByTestId('plan-why')).toHaveTextContent('не подключён');
    expect(within(dialog).getByTestId('archive-plan-jobs')).toHaveTextContent('диск не подключён');
    expect(within(dialog).getByTestId('archive-confirm')).toBeDisabled();
  });

  it('только смотреть: записи погашены причиной', async () => {
    server.use(
      mockGet('/api/health', {
        ...fixtures.health,
        writes: false,
        writes_reason: 'рабочая копия на ветке cc-api, а не main',
      }),
    );
    await open();
    for (const id of ['pool-release', 'journals', 'archive'])
      await waitFor(() =>
        expect(screen.getByTestId(`${id}-open`)).toHaveAttribute('aria-disabled', 'true'),
      );
  });

  it('пока фабрика считает — скелетоны формы блоков, не «Читаю…»', async () => {
    server.use(
      http.get('*/api/maintenance/pool', async () => {
        await delay('infinite');
      }),
    );
    renderApp('/maintenance');
    const pool = await screen.findByTestId('pool');
    const pending = await within(pool).findByRole('status');
    expect(pending).toHaveAttribute('aria-busy', 'true');
    expect(pending).toHaveTextContent('Фабрика считает пул…');
    expect(pending.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(3);
  });

  it('что фабрика делает только сама — названия словами, почему — под «Подробнее»', async () => {
    await open();
    const off = await screen.findByTestId('maintenance-not-here');
    expect(off).toHaveTextContent('Чистка временных файлов машины');
    expect(plainText(off)).not.toMatch(/\.sh|\$TMPDIR/);
  });
});
