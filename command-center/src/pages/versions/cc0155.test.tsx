// CC-0155 (договор 0.70.0): процесс cc-api в `GET /api/version` — когда запущен, на каком
// коммите, не отстал ли от кода фабрики. Слова строки, решение «что показать», полоса на экране
// «Версии» (на текущем коде / на старом / не сверить), пилюля шапки и строка карточки главной.
import { screen, waitFor, within } from '@testing-library/react';

import { fixtures, versionAnswer } from '@/mocks/fixtures';
import { mockGet } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { API_PROCESS, API_STALE_PATHS } from '@/mocks/versions';
import { renderApp } from '@/test/renderApp';

import {
  apiFreshness,
  apiStartedText,
  shortCommit,
  STALE_ACTION,
  STALE_TIP,
  STALE_TITLE,
  UNKNOWN_TEXT,
} from './apiProcessText';

const AT = '2026-10-21T22:15:07Z';
const SHA = 'abc1234f5e6d7c8b9a0f1e2d3c4b5a6978695a4b';

/** Видимый текст без «подробнее». */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

const answer = (scenario: keyof typeof API_PROCESS) =>
  server.use(mockGet('/api/version', versionAnswer(scenario)));

async function openVersions() {
  renderApp('/versions');
  await screen.findByTestId('versions-agent-list');
  return screen.findByTestId('versions-api-process');
}

describe('слова процесса API', () => {
  it('«API запущен 22.10, 01:15 МСК · на коммите abc1234» — по Москве, коммит 7 знаков', () => {
    expect(apiStartedText({ started_at: AT, commit_at_start: SHA })).toBe(
      'API запущен 22.10, 01:15 МСК · на коммите abc1234',
    );
    expect(apiStartedText({ started_at: AT, commit_at_start: SHA }, { commit: false })).toBe(
      'API запущен 22.10, 01:15 МСК',
    );
    expect(apiStartedText({ started_at: AT, commit_at_start: null })).toBe(
      'API запущен 22.10, 01:15 МСК',
    );
    expect(apiStartedText({ started_at: null, commit_at_start: SHA })).toBe(
      'API запущен · на коммите abc1234',
    );
    expect(apiStartedText({ started_at: 'не время', commit_at_start: null })).toBeNull();
    expect(apiStartedText({})).toBeNull();
    expect(shortCommit(SHA)).toBe('abc1234');
    expect(shortCommit(null)).toBeNull();
  });

  it('что показать: stale → предупреждение, false → тихо, null → «не сверить», нет полей → ничего', () => {
    expect(apiFreshness(API_PROCESS.stale)).toBe('stale');
    expect(apiFreshness(API_PROCESS.fresh)).toBe('fresh');
    expect(apiFreshness(API_PROCESS.unknown)).toBe('unknown');
    expect(apiFreshness({ started_at: AT })).toBe('unknown');
    expect(apiFreshness({})).toBeNull();
    expect(STALE_TIP).toContain(STALE_TITLE);
    expect(STALE_TIP).toContain(STALE_ACTION);
  });
});

describe('экран «Версии»: процесс API', () => {
  it('на текущем коде — тихая строка, коммит только под «Подробнее»', async () => {
    const strip = await openVersions();
    expect(strip).toHaveAttribute('data-state', 'fresh');
    expect(strip).not.toHaveAttribute('role');
    expect(plainText(strip)).toBe('API запущен 22.10, 01:15 МСК · на текущем коде фабрики');
    expect(within(strip).getByText('на коммите 0000000')).toBe(
      strip.querySelector('[data-slot="more"] span'),
    );
    expect(screen.queryByText(STALE_TITLE)).toBeNull();
    expect(screen.getByTestId('api-status')).toHaveTextContent('Фабрика на связи');
  });

  it('на старом коде — предупреждение и что сделать; изменённые файлы под «Подробнее»', async () => {
    answer('stale');
    const strip = await openVersions();
    await waitFor(() => expect(strip).toHaveAttribute('data-state', 'stale'));
    expect(strip).toHaveAttribute('role', 'status');
    const plain = plainText(strip);
    expect(plain).toContain(STALE_TITLE);
    expect(plain).toContain(STALE_ACTION);
    expect(plain).toContain('API запущен 22.10, 01:15 МСК');
    expect(plain).not.toMatch(/коммит|abc1234|\.py/);
    const more = strip.querySelector('[data-slot="more"]')!;
    expect(more).toHaveTextContent('Подробнее: что изменилось');
    expect(more).not.toHaveTextContent('API запущен');
    expect(more).toHaveTextContent('на коммите abc1234');
    expect(more).toHaveTextContent('сейчас у фабрики: 5c9cb3a');
    expect(
      within(strip)
        .getAllByTestId('versions-api-stale-path')
        .map((e) => e.textContent),
    ).toEqual([...API_STALE_PATHS]);
    await waitFor(() =>
      expect(screen.getByTestId('api-status')).toHaveTextContent('API на старом коде'),
    );
  });

  it('сверить не удалось — без тревоги, «не удалось сверить»', async () => {
    answer('unknown');
    const strip = await openVersions();
    await waitFor(() => expect(strip).toHaveAttribute('data-state', 'unknown'));
    expect(strip).not.toHaveAttribute('role');
    expect(plainText(strip)).toBe(`API запущен 22.10, 01:15 МСК · ${UNKNOWN_TEXT}`);
    expect(strip.querySelector('[data-slot="more"]')).toBeNull();
    expect(screen.queryByText(STALE_TITLE)).toBeNull();
    expect(screen.getByTestId('api-status')).toHaveTextContent('Фабрика на связи');
  });

  it('API до 0.70.0 о процессе молчит — полосы нет', async () => {
    const { started_at, commit_at_start, stale, stale_paths, ...old } = fixtures.version;
    void [started_at, commit_at_start, stale, stale_paths];
    server.use(mockGet('/api/version', old));
    renderApp('/versions');
    await screen.findByTestId('versions-agent-list');
    await waitFor(() => expect(screen.getByTestId('api-status')).toHaveTextContent('на связи'));
    expect(screen.queryByTestId('versions-api-process')).toBeNull();
  });
});

describe('главная: карточка «Фабрика»', () => {
  it('на старом коде — строка «Код API: старый код», время и файлы под «подробнее»', async () => {
    answer('stale');
    renderApp();
    const card = await screen.findByTestId('factory-card');
    expect(await within(card).findByTestId('factory-api-stale')).toHaveTextContent('старый код');
    const more = card.querySelector('[data-slot="more"]')!;
    expect(more).toHaveTextContent('API запущен 22.10, 01:15 МСК · на коммите abc1234');
    expect(more).toHaveTextContent(`изменился код: ${API_STALE_PATHS.join(', ')}`);
  });

  it('на текущем коде — строки «Код API» нет', async () => {
    renderApp();
    const card = await screen.findByTestId('factory-card');
    await within(card).findByRole('heading', { name: /^Версия / });
    expect(within(card).queryByTestId('factory-api-stale')).toBeNull();
    expect(card.querySelector('[data-slot="more"]')).toHaveTextContent(
      'API запущен 22.10, 01:15 МСК',
    );
  });
});
