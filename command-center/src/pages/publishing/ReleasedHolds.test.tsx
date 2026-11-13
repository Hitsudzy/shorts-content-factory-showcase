// «Публикация» → «Холды публикации», CC-0170: свёрнутый список «Снятые за 14 дней (N)» на
// `GET /api/publish/holds/released` — строка фабрики `line_ru`, когда и тема/ролик, отметка
// снова поставленного правилом сцен, сцены флага; `problem` — как есть.
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { publish } from '@/mocks/handlers';
import { REEL, SCENE_REOPENED, SCIENCE, TECH, WHOLE_TOPIC_HOLD } from '@/mocks/publish';
import { renderApp } from '@/test/renderApp';

async function released(channel: string) {
  renderApp(`/publishing?channel=${channel}`);
  const holds = await screen.findByTestId('holds');
  return { holds, list: await within(holds).findByTestId('holds-released') };
}

describe('CC-0170: снятые холды за 14 дней', () => {
  it('свёрнут, счёт в заголовке, строки фабрики новыми первыми, отметка снова поставленного', async () => {
    const user = userEvent.setup();
    const { holds, list } = await released(TECH);
    expect(list.tagName).toBe('DETAILS');
    expect(list).not.toHaveAttribute('open');
    const summary = within(list).getByTestId('holds-released-summary');
    expect(summary).toHaveTextContent('Снятые за 14 дней (3)');
    await user.click(summary);
    expect(list).toHaveAttribute('open');
    const rows = within(list).getAllByTestId('hold-released');
    expect(rows.map((r) => within(r).getByTestId('hold-released-line').textContent)).toEqual([
      'Удержание снова стоит: флаг на s2, в ролике s2, нужна подпись',
      'Удержание снято: флаг на s2, в ролике s1, подпись не нужна',
      'Удержание снято: посмотрел: без подробностей, источники — новости',
    ]);
    expect(rows.map((r) => r.dataset.state)).toEqual(['reopened', 'released', 'released']);
    // Отметка — только у снова поставленного.
    expect(within(rows[0]!).getByTestId('hold-reopened')).toHaveTextContent(
      'снова стоит, нужна подпись',
    );
    expect(within(rows[1]!).queryByTestId('hold-reopened')).not.toBeInTheDocument();
    // Когда и тема/ролик.
    expect(within(rows[0]!).getByTestId('hold-released-when')).toHaveTextContent(
      `снова поставлен 09.10, 08:30 · тема ${SCENE_REOPENED.topic_id} · ролик ${SCENE_REOPENED.topic_id}-script2`,
    );
    expect(within(rows[1]!).getByTestId('hold-released-when')).toHaveTextContent(/^снят 09\.10/);
    // Сцены флага: у темы целиком — «вся тема».
    expect(within(rows[2]!).getByTestId('hold-scenes')).toHaveTextContent(
      'флаг чувствительности: вся тема',
    );
    expect(within(rows[2]!).getByTestId('hold-released-when')).toHaveTextContent(
      WHOLE_TOPIC_HOLD.topic_id,
    );
    // Снова поставленный — и в открытых, со сценами флага.
    expect(within(holds).getByText('Открытых: 1')).toBeInTheDocument();
    const open = within(holds).getByTestId('hold');
    expect(within(open).getByTestId('hold-scenes')).toHaveTextContent('сцена s2');
    expect(publish.state.calls).toContain(`/api/publish/holds/released?channel=${TECH}&days=14`);
  });

  it('у Reel — снятый подписью раньше; ничего не пишется', async () => {
    const { list } = await released(REEL);
    expect(within(list).getByTestId('holds-released-summary')).toHaveTextContent(
      'Снятые за 14 дней (1)',
    );
    expect(within(list).getByTestId('hold-released-line')).toHaveTextContent(
      'Удержание снято: источники сверены пользователем: дата верная',
    );
    expect(publish.writes.state.calls).toEqual([]);
  });

  it('пустой список — «(0)» и строка, что ничего не снято', async () => {
    const { list } = await released(SCIENCE);
    expect(within(list).getByTestId('holds-released-summary')).toHaveTextContent(
      'Снятые за 14 дней (0)',
    );
    expect(within(list).queryAllByTestId('hold-released')).toHaveLength(0);
    expect(within(list).getByTestId('holds-released-empty')).toHaveTextContent(
      'За 14 дней ни один холд не снят.',
    );
  });

  it('реестр не читается — строка фабрики как есть, без списка', async () => {
    publish.state.releasedProblem = 'publish/publication-holds.json: not JSON';
    renderApp(`/publishing?channel=${TECH}`);
    const holds = await screen.findByTestId('holds');
    expect(await within(holds).findByTestId('holds-released-problem')).toHaveTextContent(
      'Снятые за 14 дней не прочитать: publish/publication-holds.json: not JSON',
    );
    expect(within(holds).queryByTestId('holds-released')).not.toBeInTheDocument();
  });
});
