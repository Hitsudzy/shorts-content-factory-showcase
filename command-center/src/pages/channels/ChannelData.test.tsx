import { screen, within } from '@testing-library/react';

import { ENDING_COMMIT_REFUSED } from '@/mocks/channelData';
import { channels } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const open = async (id: string) => {
  renderApp(`/channels/${id}?tab=data`);
  return screen.findByTestId('channel-data');
};

describe('«Данные канала» (CC-0115 → CC-0101/0102)', () => {
  it('Reel: концовка вручную, источники по уровням, партнёрской таблицы нет', async () => {
    const d = await open('example-film');
    const ending = await within(d).findByTestId('ending');
    expect(ending).toHaveTextContent('есть');
    expect(within(ending).getByTestId('ending-probe')).toHaveTextContent(
      '3 с · 1080×1920 · 30 к/с · со звуком',
    );
    expect(within(ending).getByTestId('ending-render')).toHaveTextContent(
      'Собрана вручную — из бренда канала её не пересобрать.',
    );
    const src = await within(d).findByTestId('fact-sources');
    const tiers = within(src).getAllByTestId('sources-tier');
    expect(tiers[0]).toHaveTextContent('Основные издания: 6');
    expect(tiers[0]).toHaveTextContent('variety.com');
    expect(tiers[1]).toHaveTextContent('Только для ссылки: 2');
    expect(within(src).getByTestId('sources-any')).toHaveTextContent(
      'интервью создателей — с прямой цитатой',
    );
    expect(within(src).getByTestId('sources-never')).toHaveTextContent('imdb.com');
    expect(within(src).getByTestId('sources-kinds')).toHaveTextContent(
      'съёмки, кассовые сборы, кастинг, выход, приём зрителей, скандал, другое',
    );
    // id изданий — только под «подробнее».
    expect(within(src).getByText('1: hollywood_reporter')).not.toBeVisible();
    const aff = await within(d).findByTestId('affiliate');
    expect(aff).toHaveTextContent('выключены');
    expect(aff).toHaveTextContent('Таблицы партнёрских ссылок у канала нет.');
    // Вкладка данных — без кнопок сохранения.
    expect(screen.queryByTestId('save-bar')).not.toBeInTheDocument();
  });

  it('Tech: концовка не собрана, но собирается; две партнёрские ссылки', async () => {
    const d = await open('example-tech');
    const ending = await within(d).findByTestId('ending');
    expect(ending).toHaveTextContent('не собрана');
    expect(within(ending).getByTestId('ending-render')).toHaveTextContent(
      'Её можно собрать из бренда канала.',
    );
    const aff = await within(d).findByTestId('affiliate');
    expect(within(aff).getByTestId('affiliate-counts')).toHaveTextContent(
      'программ: 1 · товаров: 2',
    );
    expect(within(aff).getByTestId('affiliate-products')).toHaveTextContent(
      'Pixel 10 ProAmazon Associates (US)',
    );
  });

  it('Science: ошибки фабрики в списке источников; список не читается — ошибка', async () => {
    const d = await open('example-science');
    const src = await within(d).findByTestId('fact-sources');
    expect(within(src).getByTestId('list-errors')).toHaveTextContent(
      'Фабрика нашла в списке 2 ошибки',
    );
    // Виды фактов — словами; неизвестный код — «другой вид факта», коды — под «подробнее».
    const kinds = within(src).getByTestId('sources-kinds');
    expect(kinds).toHaveTextContent(
      'измерение, открытие, миссия, рекорд, история, другое, другой вид факта',
    );
    expect(kinds).not.toHaveTextContent(/discovery|mission|eclipse_chase/);
    expect(within(src).getByText(/^виды фактов: measurement, discovery/)).not.toBeVisible();
  });

  it('список не читается — слова фабрики', async () => {
    channels.data.broken = true;
    const d = await open('example-film');
    expect(await within(d).findByText('Источники фактов не прочитать')).toBeInTheDocument();
    expect(d).toHaveTextContent('Список канала не читается.');
  });

  it('CC-0161: концовка собрана, но git отказал в коммите — заметная строка, git — под «подробнее»', async () => {
    channels.data.ending.lastRun['example-tech'] = ENDING_COMMIT_REFUSED('example-tech');
    const d = await open('example-tech');
    const ending = await within(d).findByTestId('ending');
    expect(ending).toHaveTextContent('есть');
    expect(within(ending).getByTestId('ending-commit-refused')).toHaveTextContent(
      'Концовка собрана, но не записана в историю изменений — в папке фабрики остались незаписанные правки. Скажите фабрике.',
    );
    const detail = within(ending).getByTestId('ending-commit-detail');
    expect(detail).not.toBeVisible();
    expect(detail).toHaveTextContent(
      "git отказал в коммите: fatal: Unable to create '.git/index.lock'",
    );
  });

  it('CC-0161: без отказа коммита строки нет', async () => {
    channels.data.ending.lastRun['example-tech'] = {
      ...ENDING_COMMIT_REFUSED('example-tech'),
      commit_refused: null,
    };
    const d = await open('example-tech');
    const ending = await within(d).findByTestId('ending');
    expect(within(ending).queryByTestId('ending-commit-refused')).toBeNull();
  });
});
