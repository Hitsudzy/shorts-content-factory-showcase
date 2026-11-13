import { screen, within } from '@testing-library/react';

import { renderApp } from '@/test/renderApp';

describe('«Мемы»: кандидаты в банк (CC-0115 → CC-0103)', () => {
  it('свой банк Tech: сводка, группы по растяжке, состояние; id и пути — под «подробнее»', async () => {
    renderApp('/memes?channel=example-tech');
    const card = await screen.findByTestId('meme-candidates');
    const summary = await within(card).findByTestId('candidates-summary');
    expect(summary).toHaveTextContent(
      'Ждут вашего «да»: 2 · проходят: 6 · малы: 2 · без размеров: 1',
    );
    expect(summary).toHaveTextContent('Скачать: 3 файла');
    expect(summary).toHaveTextContent('скопировать из банка ExampleFilm: 2 файла, без скачивания');
    const groups = within(card).getAllByTestId('candidates-group');
    expect(groups.map((g) => g.dataset.group)).toEqual(['pass', 'fail', 'unknown']);
    expect(groups[0]).toHaveAttribute('open');
    expect(groups[1]).not.toHaveAttribute('open');
    const first = within(groups[0]!).getAllByTestId('candidate')[0]!;
    expect(first).toHaveTextContent('This Is Fine');
    expect(first).toHaveTextContent('580×282 · растяжка ×1,86 из ×2,25');
    expect(within(first).getByTestId('candidate-status')).toHaveTextContent('в банке, ждёт «да»');
    expect(card).toHaveTextContent('Предложено в банк');
    expect(within(card).getByText(/^«да» возьмёт: this-is-fine, drake$/)).not.toBeVisible();
  });

  it('банк по умолчанию — списка нет', async () => {
    renderApp('/memes?channel=example-film');
    const card = await screen.findByTestId('meme-candidates');
    expect(await within(card).findByText('Кандидатов нет')).toBeInTheDocument();
    expect(card).toHaveTextContent('У банка нет списка кандидатов');
  });
});
