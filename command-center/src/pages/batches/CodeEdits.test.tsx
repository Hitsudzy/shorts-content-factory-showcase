// CC-0111 (CF-0713): стадия батча изменила код фабрики — заметное предупреждение на странице
// батча со стадией словами и файлами плашками кода, пометка в списке «Батчи» и на главной.
import { screen, waitFor, within } from '@testing-library/react';

import { FOOTAGE_CODE_EDIT, RUNNING, SCRIPTS_CODE_EDIT } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

import { editFiles, editHead } from './codeEditsText';

const card = async (batch: string) => {
  await waitFor(() =>
    expect(screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)).toBeTruthy(),
  );
  return screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)!;
};

describe('CC-0111: слова правки кода', () => {
  it('стадия — словами, файлы — от корня фабрики', () => {
    expect(editHead(FOOTAGE_CODE_EDIT)).toBe(
      'Стадия «Разметка футажа» (кадр «Футаж») изменила код фабрики',
    );
    // Имя стадии совпадает с кадром — без скобок.
    expect(editHead({ ...FOOTAGE_CODE_EDIT, stage: 'video-editor' })).toBe(
      'Стадия «Монтаж» изменила код фабрики',
    );
    expect(editHead({ ...FOOTAGE_CODE_EDIT, stage: null })).toBe(
      'Стадия батча изменила код фабрики',
    );
    expect(editFiles(FOOTAGE_CODE_EDIT)).toEqual([
      'agents/footage-indexer/scripts/source_rights.py',
    ]);
    // Без `files` — собраны из `edits`: файлы агента — с его каталогом, корня — как есть.
    expect(
      editFiles({
        ...FOOTAGE_CODE_EDIT,
        files: [],
        edits: [
          { repo: 'agents/video-editor', files: ['scripts/render.py'] },
          { repo: 'root', files: ['shared/runlog/funnel.py'] },
        ],
      }),
    ).toEqual(['agents/video-editor/scripts/render.py', 'shared/runlog/funnel.py']);
  });
});

describe('CC-0111: правка кода на экране', () => {
  it('страница батча: предупреждение, файлы плашками, что будет дальше; строка фабрики — под «Подробнее»', async () => {
    batches.setCodeEdits(RUNNING, [FOOTAGE_CODE_EDIT, SCRIPTS_CODE_EDIT]);
    renderApp('/batches');
    const c = await card(RUNNING);
    const block = await within(c).findByTestId('code-edits');
    expect(block).toHaveAttribute('role', 'alert');
    const rows = within(block).getAllByTestId('code-edit');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(
      'Стадия «Разметка футажа» (кадр «Футаж») изменила код фабрики:',
    );
    expect(rows[1]).toHaveTextContent('Стадия «Проверка сценариев» изменила код фабрики:');
    // Файлы — плашками кода, не предложением.
    const files = within(rows[0]!).getAllByTestId('code-edit-file');
    expect(files.map((f) => f.tagName)).toEqual(['CODE']);
    expect(files[0]).toHaveTextContent('agents/footage-indexer/scripts/source_rights.py');
    expect(within(rows[1]!).getAllByTestId('code-edit-file')).toHaveLength(2);
    expect(within(block).getByTestId('code-edits-consequence')).toHaveTextContent(
      'Следующий батч не запустится, пока правку не закоммитят или не откатят. Этот прогон фабрика не останавливает, только предупреждает.',
    );
    // Коды стадий, строка фабрики, источник, задача, коммиты — только под «Подробнее».
    const more = block.querySelector('details')!;
    expect(more).not.toHaveAttribute('open');
    expect(more).toHaveTextContent(
      'строка фабрики: agents/footage-indexer: scripts/source_rights.py',
    );
    expect(more).toHaveTextContent('CF-0713');
    expect(more).toHaveTextContent('источник: из журнала событий');
    expect(more).toHaveTextContent('root: коммит 4f1c2a9e0b → 9a8b7c6d5e');
    for (const r of rows) {
      expect(r).not.toHaveTextContent('footage-indexer.s0');
      expect(r).not.toHaveTextContent('CF-0713');
    }
    // Пометка в шапке карточки.
    expect(within(c).getByTestId('code-edits-mark')).toHaveTextContent('правки кода: 2');
  });

  it('правок нет — ни предупреждения, ни пометки', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    await within(c).findByTestId('batch-inside');
    expect(within(c).queryByTestId('code-edits')).toBeNull();
    expect(within(c).queryByTestId('code-edits-mark')).toBeNull();
  });

  it('главная: пометка и строка на карточке батча', async () => {
    batches.setCodeEdits(RUNNING, [FOOTAGE_CODE_EDIT]);
    renderApp('/');
    const home = await screen.findByTestId('batch-card');
    await waitFor(() => expect(within(home).getByTestId('code-edits-mark')).toBeInTheDocument());
    expect(within(home).getByTestId('code-edits-mark')).toHaveTextContent('правка кода');
    expect(within(home).getByTestId('home-code-edits')).toHaveTextContent(
      'следующий батч не запустится',
    );
  });
});
