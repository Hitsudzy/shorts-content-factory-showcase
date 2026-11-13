// «Версии и агенты» (CC-0031): выпуск фабрики, центр, что в работе, агенты против пинов —
// расхождение словами (без строк фабрики и коммитов на виду), «всё на пинах», ничего не в работе,
// лок не прочитан, замечание вне агентов, отказ API, скелетон, «Проверить заново» (`?fresh=true`).
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http } from 'msw';

import { versions } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { agentName, agentsTitle, branchText, branchTip, driftText, syncFixes, TIP } from './format';

/** Видимый текст без «подробнее». */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

async function open() {
  renderApp('/versions');
  await screen.findByTestId('versions-agent-list');
}

const agent = (name: string) =>
  screen.getAllByTestId('versions-agent').find((e) => e.getAttribute('data-agent') === name)!;

describe('экран «Версии и агенты»', () => {
  it('выпуск, центр и что в работе — словами; коммиты и ветки только под «Подробнее»', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Версии и агенты');
    expect(screen.getByTestId('versions-release')).toHaveTextContent('2.3.4');
    expect(screen.getByTestId('versions-readme')).toHaveTextContent('2.3');
    expect(screen.getByTestId('versions-branch')).toHaveTextContent('основная ветка');
    expect(screen.getByTestId('versions-center-version')).toHaveTextContent('0.3.1');
    const work = screen.getByTestId('versions-work');
    expect(within(work).getByTestId('versions-work-item')).toHaveTextContent('2.4');
    expect(within(work).getByRole('heading')).toHaveTextContent('1 версия готовится');
    const page = plainText(document.querySelector('main')!);
    expect(page).not.toMatch(
      /release\/|agents\/|scripts\/|[0-9a-f]{12}|HEAD|uncommitted|\bgit\b|коммит|не на пине/i,
    );
    expect(page).toContain('Версия по описанию фабрики');
    expect(screen.queryByText(/Скоро · версия/)).toBeNull();
  });

  it('расхождение: полоса сверху одним словом «расходится», число — только в заголовке агентов', async () => {
    await open();
    const sum = screen.getByTestId('versions-summary');
    expect(sum).toHaveAttribute('data-drift', '1');
    expect(sum).toHaveTextContent('Агенты расходятся с пинами');
    expect(sum).toHaveTextContent('Что сделать — в строке каждого агента');
    expect(sum).not.toHaveTextContent('из 5');
    // Синхронизация чинит только агента на чужой ветке — его и называет; правки она не чинит.
    expect(screen.getByTestId('versions-sync')).toHaveTextContent(
      'вернёт на пин: Content Researcher.',
    );
    expect(screen.getByTestId('versions-sync')).not.toHaveTextContent('Video Editor');
    expect(screen.getByRole('heading', { name: '2 из 5 расходятся с пином' })).toBeInTheDocument();
    const rows = screen.getAllByTestId('versions-agent');
    expect(rows.slice(0, 2).map((r) => r.getAttribute('data-ok'))).toEqual(['0', '0']);
    expect(within(agent('content-researcher')).getByTestId('versions-agent-why')).toHaveTextContent(
      'стоит на ветке выпуска 2.4, а не на v2.3',
    );
    expect(within(agent('video-editor')).getByTestId('versions-agent-why')).toHaveTextContent(
      'в 2 файлах правки не зафиксированы',
    );
    expect(agent('video-editor')).toHaveTextContent('Синхронизация тут не поможет');
    expect(within(agent('footage-indexer')).getByText('на пине')).toBeInTheDocument();
    expect(within(agent('footage-indexer')).queryByTestId('versions-agent-why')).toBeNull();
    expect(agent('trend-hunter')).toHaveTextContent('Trend Hunter');
  });

  it('всё на пинах и ничего не в работе', async () => {
    versions.clean();
    versions.state.inWork = [];
    await open();
    expect(screen.getByTestId('versions-summary')).toHaveAttribute('data-drift', '0');
    expect(screen.getByRole('heading', { name: 'Все 5 на своих пинах' })).toBeInTheDocument();
    expect(screen.queryAllByTestId('versions-agent-drift')).toHaveLength(0);
    expect(screen.getByTestId('versions-work-empty')).toHaveTextContent(
      'ни один выпуск не собирается',
    );
    expect(screen.getByRole('heading', { name: 'Ничего не готовится' })).toBeInTheDocument();
  });

  it('лок не прочитан — ошибка в карточке агентов, полосы нет', async () => {
    versions.state.lockError = 'no agents.lock.json in the root';
    renderApp('/versions');
    expect(await screen.findByText('Фабрика не прочитала пины агентов')).toBeInTheDocument();
    expect(screen.queryByTestId('versions-summary')).toBeNull();
    expect(screen.getByTestId('versions-factory')).toBeInTheDocument();
  });

  it('замечание вне агентов — отдельная карточка словами, строка фабрики под «Подробнее»', async () => {
    versions.clean();
    versions.state.rootLines = true;
    await open();
    const root = screen.getByTestId('versions-root');
    expect(within(root).getByTestId('versions-root-lines')).toHaveTextContent(
      'Битая ссылка на общий файл фабрики',
    );
    expect(plainText(root)).not.toContain('shared/inserts');
    expect(screen.getByTestId('versions-summary')).toHaveAttribute('data-drift', '1');
  });

  it('центр не на пине — «расходится» у центра', async () => {
    versions.state.centerOff = true;
    await open();
    expect(screen.getByTestId('versions-center-drift')).toHaveTextContent('расходится');
  });

  it('API не ответил — ошибка с «Повторить», повтор читает заново', async () => {
    versions.state.refuse = true;
    const user = userEvent.setup();
    renderApp('/versions');
    expect(await screen.findByText('Версии не прочитать')).toBeInTheDocument();
    versions.state.refuse = false;
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByTestId('versions-agent-list')).toBeInTheDocument();
  });

  it('пока ответа нет — скелетон той же формы', async () => {
    server.use(
      http.get('*/api/versions', async () => {
        await delay('infinite');
      }),
    );
    renderApp('/versions');
    const pending = await screen.findByTestId('versions-pending');
    expect(pending).toHaveAttribute('role', 'status');
    expect(pending).toHaveTextContent('Спрашиваю фабрику о версиях…');
    expect(pending.querySelectorAll('[data-slot="pending-part"]').length).toBeGreaterThan(3);
  });

  it('«Проверить заново» — свежая проверка, время обновилось', async () => {
    const user = userEvent.setup();
    await open();
    const checked = screen.getByTestId('versions-checked');
    expect(checked).toHaveTextContent('14 октября, 09:40');
    await user.click(screen.getByTestId('versions-recheck'));
    await waitFor(() => expect(checked).toHaveTextContent('14 октября, 09:41'));
    expect(versions.state.calls).toContain('/api/versions?fresh=true');
    expect(checked).not.toHaveTextContent('сохранённый ответ');
  });
});

describe('слова экрана', () => {
  const row = {
    agent: 'x',
    path: 'agents/x',
    rev: 'v2.3',
    sha: 'a'.repeat(40),
    head: 'a'.repeat(40),
    branch: null,
    dirty: [],
    ok: false,
    why: null,
    line: null,
    mark: null,
  };
  it.each([
    [{ head: null }, 'не скачан в эту копию фабрики'],
    [{ head: null, sha: null }, 'версии v2.3 нет в истории агента — её не скачать'],
    [{ head: 'b'.repeat(40), branch: 'main' }, 'стоит на основной ветке, а не на v2.3'],
    [{ head: 'b'.repeat(40), branch: 'fix' }, 'стоит на своей ветке, а не на v2.3'],
    [{ head: 'b'.repeat(40) }, 'стоит на другой версии кода, а не на v2.3'],
    [{ dirty: null }, 'не проверить, есть ли незафиксированные правки'],
    [{ dirty: ['a'] }, 'в 1 файле правки не зафиксированы'],
    [{ dirty: Array(5).fill('a') }, 'в 5 файлах правки не зафиксированы'],
    [{}, 'ссылки на общие файлы не в порядке'],
  ])('%j → %s', (patch, text) => {
    expect(driftText({ ...row, ...patch })).toBe(text);
  });

  it('синхронизация чинит всё, кроме незафиксированных правок', () => {
    expect(syncFixes({ ...row, dirty: ['a'] })).toBe(false);
    expect(syncFixes({ ...row, head: 'b'.repeat(40), dirty: ['a'] })).toBe(true);
    expect(syncFixes({ ...row, head: null })).toBe(true);
    expect(syncFixes({ ...row, ok: true })).toBe(false);
  });

  it('заголовок агентов — одно слово «расходится»', () => {
    expect(agentsTitle(1, 5)).toBe('1 из 5 расходится с пином');
    expect(agentsTitle(2, 5)).toBe('2 из 5 расходятся с пином');
    expect(agentsTitle(0, 5)).toBe('Все 5 на своих пинах');
  });

  it('на пине — без слов; имена и ветки', () => {
    expect(driftText({ ...row, ok: true })).toBeNull();
    expect(agentName('footage-indexer')).toBe('Footage Indexer');
    expect(agentName('new-agent')).toBe('New Agent');
    expect(branchText('release/2.4')).toBe('ветка выпуска 2.4');
    expect(branchText(null)).toBe('без ветки, на отдельной версии кода');
    expect(branchTip('release/2.4')).toBe(TIP.release);
    expect(branchTip('main')).toBe(TIP.main);
    expect(branchTip('fix')).toBeNull();
  });
});
