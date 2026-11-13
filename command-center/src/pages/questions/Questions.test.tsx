// «Вопросы» (CC-0017): открытые сверху, ответ в карточке, «решено» с одним подтверждением,
// история, фильтры по источнику и каналу, счётчик открытых на табе и на главной; отказы — словами;
// «только смотреть» — кнопки погашены и записи не уходят.
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, questions } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const cards = () => screen.getAllByTestId('question');
const card = (qid: string) => screen.getAllByTestId('question').find((c) => c.dataset.qid === qid)!;
const tab = () => screen.getByRole('link', { name: 'Вопросы' });
/** Число на табе «Вопросы» (для диктора скрыто — оно в тултипе таба). */
const tabCount = () => tab().querySelector('[data-slot="count"]')?.textContent ?? null;

/** Видимый текст без «подробнее»: номера и имена скриптов живут только там. */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

async function open(path = '/questions') {
  const user = userEvent.setup();
  renderApp(path);
  await screen.findByTestId('open-questions');
  return user;
}

describe('CC-0017: экран «Вопросы»', () => {
  it('открытые сверху (новые первыми), под ними — с ответом, ниже — история', async () => {
    await open();
    expect(cards().map((c) => c.dataset.qid)).toEqual(['Q9', 'Q8', 'Q6', 'Q7']);
    expect(cards().map((c) => c.dataset.status)).toEqual(['open', 'open', 'open', 'answered']);
    expect(within(card('Q9')).getByTestId('question-source')).toHaveTextContent(
      'Охотник за трендами',
    );
    expect(within(card('Q9')).getByTestId('question-channel')).toHaveTextContent('ExampleFilm');
    expect(within(card('Q7')).getByTestId('question-answer')).toHaveTextContent(
      'Подождать неделю, потом решим.',
    );
    const history = screen.getByTestId('history');
    await waitFor(() =>
      expect(
        within(history)
          .getAllByTestId('history-item')
          .map((i) => i.dataset.qid),
      ).toEqual(['Q5', 'Q4', 'Q3']),
    );
    const archive = within(history)
      .getAllByTestId('history-item')
      .find((i) => i.dataset.qid === 'Q4')!;
    expect(within(archive).getByTestId('history-resolved')).toHaveTextContent(
      'Архив публикаций · отметки Studio внесены, архив собран',
    );
    // Номера, ключи событий, имена скриптов и пути — только под «подробнее».
    const main = screen.getByRole('main');
    for (const id of ['Q9', 'trend-hunter', 'publisher-auth', 'oauth-token', 'agents/publisher'])
      expect(plainText(main)).not.toContain(id);
    expect(
      within(card('Q6')).getByText('ссылка: agents/publisher/publisher_auth.py'),
    ).toBeInTheDocument();
  });

  it('ответ в карточке: «Отправить» — запись, тост, вопрос уходит к отвеченным, счётчик падает', async () => {
    const user = await open();
    expect(tabCount()).toBe('3');
    const q = card('Q9');
    const send = within(q).getByTestId('answer-send');
    expect(send).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(q).getByTestId('answer-text'), 'Да, взять Entourage');
    expect(send).not.toHaveAttribute('aria-disabled');
    await user.click(send);
    expect(await screen.findByText('Ответ отправлен фабрике')).toBeInTheDocument();
    await waitFor(() => expect(card('Q9').dataset.status).toBe('answered'));
    expect(within(card('Q9')).getByTestId('question-answer')).toHaveTextContent(
      'Да, взять Entourage',
    );
    expect(questions.writes).toEqual([
      {
        path: '/api/questions/Q9/answer',
        body: { text: 'Да, взять Entourage', by: 'user', accept: false },
      },
    ]);
    await waitFor(() => expect(tabCount()).toBe('2'));
    expect(cards().map((c) => c.dataset.qid)).toEqual(['Q8', 'Q6', 'Q9', 'Q7']);
  });

  it('Ctrl+Enter тоже отправляет; «Изменить ответ» — ответить ещё раз', async () => {
    const user = await open();
    await user.type(within(card('Q8')).getByTestId('answer-text'), 'Снять тему');
    await user.keyboard('{Control>}{Enter}{/Control}');
    await waitFor(() => expect(card('Q8').dataset.status).toBe('answered'));
    await user.click(within(card('Q7')).getByTestId('answer-again'));
    const text = within(card('Q7')).getByTestId('answer-text');
    expect(text).toHaveValue('Подождать неделю, потом решим.');
    await user.clear(text);
    await user.type(text, 'Сменить шаблон');
    await user.click(within(card('Q7')).getByTestId('answer-send'));
    await waitFor(() =>
      expect(within(card('Q7')).getByTestId('question-answer')).toHaveTextContent('Сменить шаблон'),
    );
  });

  it('«Решено…» — одно подтверждение с заметкой; вопрос уходит в историю', async () => {
    const user = await open();
    await user.click(within(card('Q6')).getByTestId('resolve-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Отметить вопрос решённым?');
    expect(dialog).toHaveTextContent('Доступ к YouTube у канала ExampleFilm истекает');
    await user.type(within(dialog).getByTestId('resolve-note'), 'переразрешил');
    await user.click(within(dialog).getByTestId('resolve-confirm'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(await screen.findByText('Вопрос отмечен решённым')).toBeInTheDocument();
    await waitFor(() => expect(cards().map((c) => c.dataset.qid)).not.toContain('Q6'));
    const history = screen.getByTestId('history');
    await waitFor(() =>
      expect(within(history).getAllByTestId('history-item')[0]!.dataset.qid).toBe('Q6'),
    );
    expect(within(history).getAllByTestId('history-resolved')[0]).toHaveTextContent(
      'вами · переразрешил',
    );
    expect(questions.writes.at(-1)).toEqual({
      path: '/api/questions/Q6/resolve',
      body: { note: 'переразрешил', by: 'user' },
    });
    await waitFor(() => expect(tabCount()).toBe('2'));
  });

  it('отказы словами: вопрос уже решён, вопроса нет, пустой ответ; строка фабрики — под «подробнее»', async () => {
    const user = await open();
    questions.next = { status: 409, detail: 'question Q9 is already resolved' };
    await user.type(within(card('Q9')).getByTestId('answer-text'), 'да');
    await user.click(within(card('Q9')).getByTestId('answer-send'));
    const err = await within(card('Q9')).findByTestId('answer-error');
    expect(err).toHaveTextContent('Вопрос уже решён');
    expect(err).toHaveTextContent('Ответить на решённый вопрос нельзя');
    expect(within(err).getByText(/question Q9 is already resolved/)).toBeInTheDocument();
    expect(plainText(err)).not.toContain('Q9');

    questions.next = { status: 422, detail: 'an answer needs a text' };
    await user.type(within(card('Q9')).getByTestId('answer-text'), '!');
    await user.click(within(card('Q9')).getByTestId('answer-send'));
    expect(await within(card('Q9')).findByTestId('answer-error')).toHaveTextContent('Ответ пустой');

    questions.next = { status: 404, detail: 'no question Q8' };
    await user.click(within(card('Q8')).getByTestId('resolve-open'));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByTestId('resolve-confirm'));
    expect(await within(dialog).findByTestId('resolve-error')).toHaveTextContent(
      'Такого вопроса больше нет',
    );
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('«только смотреть»: «Отправить» и «Решено…» погашены причиной, записи не уходят', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const user = await open();
    const q = card('Q9');
    await user.type(within(q).getByTestId('answer-text'), 'да');
    const send = within(q).getByTestId('answer-send');
    await waitFor(() => expect(send).toHaveAttribute('data-writes', 'off'));
    await user.click(send);
    await user.keyboard('{Control>}{Enter}{/Control}');
    const resolve = within(q).getByTestId('resolve-open');
    expect(resolve).toHaveAttribute('data-writes', 'off');
    await user.click(resolve);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(questions.writes).toEqual([]);
  });

  it('409 not_working_factory посреди сессии — сказано словами фабрики', async () => {
    const user = await open();
    questions.readOnly = true;
    await user.type(within(card('Q9')).getByTestId('answer-text'), 'да');
    await user.click(within(card('Q9')).getByTestId('answer-send'));
    expect(await within(card('Q9')).findByTestId('answer-error')).toHaveTextContent(
      'Только смотреть: это рабочая копия разработки',
    );
  });

  it('CC-0162: два выбора подряд до перерисовки — оба фильтра остаются', async () => {
    await open();
    // Оба — в одном act: второй выбор приходит, пока экран ещё не перерисован после первого.
    act(() => {
      fireEvent.change(screen.getByTestId('filter-source'), {
        target: { value: 'trend-hunter' },
      });
      fireEvent.change(screen.getByTestId('filter-channel'), {
        target: { value: 'example-film' },
      });
    });
    await waitFor(() => expect(cards().map((c) => c.dataset.qid)).toEqual(['Q9']));
    expect(screen.getByTestId('filter-source')).toHaveValue('trend-hunter');
    expect(screen.getByTestId('filter-channel')).toHaveValue('example-film');
  });

  it('фильтры по источнику и каналу — в адресе; «Сбросить фильтры»', async () => {
    const user = await open();
    await user.selectOptions(screen.getByTestId('filter-source'), 'Доступ к YouTube');
    expect(cards().map((c) => c.dataset.qid)).toEqual(['Q6']);
    await user.selectOptions(screen.getByTestId('filter-source'), '');
    await user.selectOptions(screen.getByTestId('filter-channel'), 'ExampleTech');
    expect(cards().map((c) => c.dataset.qid)).toEqual(['Q8']);
    await user.selectOptions(screen.getByTestId('filter-channel'), 'Без канала (общие)');
    expect(screen.getByText('Под фильтр ничего не попало')).toBeInTheDocument();
    expect(screen.queryAllByTestId('question')).toHaveLength(0);
    const history = screen.getByTestId('history');
    expect(
      within(history)
        .getAllByTestId('history-item')
        .map((i) => i.dataset.qid),
    ).toEqual(['Q4']);
    await user.click(screen.getByTestId('filters-reset'));
    expect(cards()).toHaveLength(4);
  });

  it('вопросов нет — так и сказано; счётчика на табе нет', async () => {
    questions.questions = [];
    renderApp('/questions');
    expect(await screen.findByText('Вопросов к вам нет')).toBeInTheDocument();
    expect(await screen.findByText('Решённых пока нет')).toBeInTheDocument();
    await screen.findByText('Ответов от вас фабрика не ждёт');
    expect(tabCount()).toBeNull();
  });

  it('список не читается — ошибка словами и «Повторить»', async () => {
    questions.listFails = 500;
    renderApp('/questions');
    const alert = (await screen.findAllByRole('alert'))[0]!;
    expect(alert).toHaveTextContent('Вопросы не прочитать');
    expect(within(alert).getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });
});

describe('CC-0017: вопросы на главной', () => {
  it('«Ждут вас» и «Фабрика спрашивает» — живые: счёт и два свежих вопроса', async () => {
    renderApp('/');
    await waitFor(() =>
      expect(screen.getByTestId('attention-questions')).toHaveTextContent(
        'Вопросов ждут вашего ответа: 3.',
      ),
    );
    const go = screen.getByRole('link', { name: /К вопросам/ });
    expect(within(go).getByLabelText('ждут ответа: 3')).toBeInTheDocument();
    const box = screen.getByTestId('questions-card');
    const items = await within(box).findAllByTestId('questions-item');
    expect(items.map((i) => i.dataset.qid)).toEqual(['Q9', 'Q8']);
    expect(items[0]).toHaveTextContent('Охотник за трендами · ExampleFilm');
    expect(within(box).getByText('Ещё 1 — на экране «Вопросы».')).toBeInTheDocument();
    expect(within(items[0]!).getByRole('link', { name: 'Ответить' })).toHaveAttribute(
      'href',
      '/questions',
    );
  });

  it('вопросов нет — «Вопросов к вам нет», без счётчика', async () => {
    questions.questions = [];
    renderApp('/');
    await waitFor(() =>
      expect(screen.getByTestId('attention-questions')).toHaveTextContent('Вопросов к вам нет.'),
    );
    expect(await screen.findByTestId('questions-none')).toHaveTextContent(
      'Фабрика ничего у вас не спрашивает.',
    );
  });
});

describe('CC-0086: предложенное решение', () => {
  it('предложение — плейсхолдером, кто и когда — мелко, «почему» — тултипом; без предложения — как раньше', async () => {
    const user = await open();
    const q9 = card('Q9');
    const field = within(q9).getByTestId('answer-text');
    expect(field).toHaveAttribute('placeholder', 'Да, взять Entourage пятой.');
    expect(field).toHaveValue('');
    expect(within(q9).getByTestId('suggestion-line')).toHaveTextContent(
      'Предложение · Охотник за трендами · 10.10',
    );
    // «·» держится со словом перед ним: ни один кусок строки не начинается с разделителя.
    const line = within(q9).getByTestId('suggestion-line');
    expect(line).not.toHaveTextContent('серым в поле');
    const pieces = [...line.querySelectorAll('[data-slot="suggestion-part"]')].map(
      (p) => p.textContent ?? '',
    );
    expect(pieces).toEqual([
      'Предложение\u00a0· ',
      'Охотник за трендами\u00a0· ',
      expect.any(String),
    ]);
    expect(pieces[2]).toMatch(/^10\.10.*\u00a0· $/);
    await user.hover(within(q9).getByTestId('suggestion-why'));
    expect((await screen.findAllByText(/меньше двух пунктов до порога/)).length).toBeGreaterThan(0);
    expect(within(card('Q8')).getByTestId('suggestion-line')).toHaveTextContent('оператор');
    // Q6 без предложения: прежний плейсхолдер, ни «принять», ни «вставить».
    const q6 = card('Q6');
    expect(within(q6).getByTestId('answer-text')).toHaveAttribute(
      'placeholder',
      'Ваш ответ — словами',
    );
    expect(within(q6).queryByTestId('suggestion-accept')).not.toBeInTheDocument();
    expect(within(q6).queryByTestId('suggestion-paste')).not.toBeInTheDocument();
    expect(within(q6).queryByTestId('suggestion-line')).not.toBeInTheDocument();
  });

  it('«Принять предложение» — одна запись {accept, suggested_at}, пометка «принято предложение»', async () => {
    const user = await open();
    await user.click(within(card('Q9')).getByTestId('suggestion-accept'));
    expect(
      await screen.findByText('Предложение принято — ответ отправлен фабрике'),
    ).toBeInTheDocument();
    expect(questions.writes).toEqual([
      {
        path: '/api/questions/Q9/answer',
        body: { by: 'user', accept: true, suggested_at: '2026-10-10T06:40:00Z' },
      },
    ]);
    await waitFor(() => expect(card('Q9').dataset.status).toBe('answered'));
    expect(within(card('Q9')).getByTestId('question-answer')).toHaveTextContent(
      'Да, взять Entourage пятой.',
    );
    expect(within(card('Q9')).getByTestId('answer-kind')).toHaveTextContent('принято предложение');
    // Q7 отвечен своим текстом при предложении, Q5 в истории — принятым предложением.
    expect(within(card('Q7')).getByTestId('answer-kind')).toHaveTextContent('свой ответ');
    const q5 = await waitFor(() =>
      within(screen.getByTestId('history'))
        .getAllByTestId('history-item')
        .find((i) => i.dataset.qid === 'Q5')!,
    );
    expect(within(q5).getByTestId('answer-kind')).toHaveTextContent('принято предложение');
  });

  it('«Вставить и поправить» — текст в поле; «принять» гаснет; «Отправить» шлёт правку', async () => {
    const user = await open();
    const q9 = card('Q9');
    await user.click(within(q9).getByTestId('suggestion-paste'));
    const field = within(q9).getByTestId('answer-text');
    expect(field).toHaveValue('Да, взять Entourage пятой.');
    await waitFor(() => expect(field).toHaveFocus());
    expect(within(q9).getByTestId('suggestion-accept')).toHaveAttribute('aria-disabled', 'true');
    await user.type(field, ' И шестой — Partition.');
    await user.click(within(q9).getByTestId('answer-send'));
    await waitFor(() => expect(card('Q9').dataset.status).toBe('answered'));
    expect(questions.writes[0]?.body).toEqual({
      text: 'Да, взять Entourage пятой. И шестой — Partition.',
      by: 'user',
      accept: false,
    });
    expect(within(card('Q9')).getByTestId('answer-kind')).toHaveTextContent('свой ответ');
  });

  it('предложение сменилось — отказ словами, ничего не записано, новое предложение в поле; второе «принять» проходит', async () => {
    const user = await open();
    await user.click(within(card('Q8')).getByTestId('suggestion-accept'));
    const err = await within(card('Q8')).findByTestId('answer-error');
    expect(err).toHaveTextContent('Предложение изменилось');
    expect(err).toHaveTextContent('ничего не записано');
    expect(card('Q8').dataset.status).toBe('open');
    await waitFor(() =>
      expect(within(card('Q8')).getByTestId('answer-text')).toHaveAttribute(
        'placeholder',
        'Снять тему и взять запасную «Pixel 10 battery» из вчерашних трендов.',
      ),
    );
    await user.click(within(card('Q8')).getByTestId('suggestion-accept'));
    await waitFor(() => expect(card('Q8').dataset.status).toBe('answered'));
    expect(questions.writes.map((w) => w.body)).toEqual([
      { by: 'user', accept: true, suggested_at: '2026-10-10T05:20:00Z' },
      { by: 'user', accept: true, suggested_at: '2026-10-10T06:55:00Z' },
    ]);
  });

  it('предложение убрали — «Предложения больше нет»', async () => {
    const user = await open();
    questions.next = {
      status: 409,
      detail: 'question Q9 has no suggestion',
      code: 'no_suggestion',
    };
    await user.click(within(card('Q9')).getByTestId('suggestion-accept'));
    expect(await within(card('Q9')).findByTestId('answer-error')).toHaveTextContent(
      'Предложения больше нет',
    );
  });

  it('«только смотреть» — «принять» погашено причиной, записей нет', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const user = await open();
    const accept = within(card('Q9')).getByTestId('suggestion-accept');
    await waitFor(() => expect(accept).toHaveAttribute('data-writes', 'off'));
    await user.click(accept);
    expect(questions.writes).toEqual([]);
  });

  it('главная: предложение одной строкой под вопросом', async () => {
    renderApp('/');
    const box = await screen.findByTestId('questions-card');
    const items = await within(box).findAllByTestId('questions-item');
    expect(within(items[0]!).getByTestId('questions-suggestion')).toHaveTextContent(
      'Предложение: Да, взять Entourage пятой.',
    );
    expect(within(box).queryByTestId('suggestion-accept')).not.toBeInTheDocument();
  });
});
