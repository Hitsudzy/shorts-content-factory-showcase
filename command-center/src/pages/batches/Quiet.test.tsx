// CC-0120: тихие решения плана прогона (`BatchDetail.quiet[]`, CF-0735) — строками журнала на
// карточке батча, не тревогой.
import { screen, waitFor, within } from '@testing-library/react';

import { RUNNING } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const card = async (batch: string) => {
  await waitFor(() =>
    expect(screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)).toBeTruthy(),
  );
  return screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)!;
};

describe('CC-0120: «пропущено тихо» на странице батча', () => {
  it('строки журнала со стадией словами и строкой фабрики; код — под «Подробнее»', async () => {
    batches.setQuiet(RUNNING, [
      {
        stage: 'studio-read-due',
        key: 'studio-read@example-film',
        line: 'Studio не прочитан — нет разрешения; взято по умолчанию, батч идёт дальше',
        took: 'skipped_no_permission',
        at: '2026-10-10T05:31:00Z',
      },
    ]);
    renderApp('/batches');
    const c = await card(RUNNING);
    const block = await within(c).findByTestId('batch-quiet');
    const line = within(block).getByTestId('batch-quiet-line');
    expect(line).toHaveTextContent('пропущено тихо: Чтение Studio — Studio не прочитан');
    expect(line).not.toHaveTextContent('studio-read-due');
    expect(line).toHaveTextContent('08:31');
    // Не тревога.
    expect(within(block).queryByRole('alert')).toBeNull();
  });

  it('тихих решений нет — блока нет', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    await within(c).findByTestId('batch-inside');
    expect(within(c).queryByTestId('batch-quiet')).toBeNull();
  });
});
