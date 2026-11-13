// CC-0120: ссылки уведомлений несут `?channel=` — «Батчи» и «Ролики» выбирают канал.
import { screen, waitFor } from '@testing-library/react';

import { renderApp } from '@/test/renderApp';

describe('CC-0120: ?channel= в адресе выбирает канал', () => {
  it('«Батчи»: канал запуска вручную — из адреса', async () => {
    renderApp('/batches?channel=example-tech');
    const select = await screen.findByTestId('launch-channel');
    expect(select).toHaveValue('example-tech');
  });

  it('«Батчи»: незнакомый канал в адресе — канал по умолчанию', async () => {
    renderApp('/batches?channel=nope');
    const select = await screen.findByTestId('launch-channel');
    expect(select).not.toHaveValue('nope');
  });

  it('«Ролики»: последний батч канала из адреса', async () => {
    renderApp('/videos?channel=example-tech');
    const picker = await screen.findByTestId('batch-picker');
    await waitFor(() => expect((picker as HTMLSelectElement).value).toMatch(/^example-tech\//));
  });

  it('«Ролики»: у канала нет прогонов в истории — так и сказано', async () => {
    renderApp('/videos?channel=example-new');
    expect(await screen.findByText(/прогонов в истории нет/)).toBeInTheDocument();
  });
});
