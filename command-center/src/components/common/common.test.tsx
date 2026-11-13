import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Button } from '@/components/ui/button';
import { TooltipProvider } from '@/components/ui/tooltip';

import { ConfirmAction } from './ConfirmAction';
import { More } from './More';
import { StatusBadge } from './Status';
import { ErrorState, Soon } from './States';
import { Tip } from './Tip';

describe('общие компоненты', () => {
  it('подтверждение: действие только после «да», «отмена» ничего не делает', async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmAction
        trigger={<Button>Остановить</Button>}
        title="Остановить батч?"
        description="Готовые ролики сохранятся."
        confirmLabel="Остановить"
        danger
        onConfirm={onConfirm}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Остановить' }));
    expect(screen.getByRole('alertdialog', { name: 'Остановить батч?' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Остановить' }));
    const dialog = screen.getByRole('alertdialog');
    await user.click(
      screen.getAllByRole('button', { name: 'Остановить' }).find((b) => dialog.contains(b))!,
    );
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('«подробнее» закрыто, пока его не открыли', async () => {
    render(
      <More>
        <span>журнал: pipeline/RUNS.md</span>
      </More>,
    );
    const details = screen.getByText('Подробнее').closest('details')!;
    expect(details.open).toBe(false);
    await userEvent.click(screen.getByText('Подробнее'));
    expect(details.open).toBe(true);
    expect(screen.getByText('журнал: pipeline/RUNS.md')).toBeVisible();
  });

  it('тултип показывается при фокусе', async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Tip content="Холд: ролик не уйдёт, пока проверка прав не снимет его">
          <button>холд</button>
        </Tip>
      </TooltipProvider>,
    );
    await userEvent.tab();
    expect(await screen.findByRole('tooltip')).toHaveTextContent(/проверка прав/);
  });

  it('ошибка: человеческий текст, причина под «подробнее», «повторить»', async () => {
    const onRetry = vi.fn();
    render(
      <ErrorState
        title="Нет связи с фабрикой"
        error={new Error('503 /api/version')}
        onRetry={onRetry}
      >
        Проверьте, что API фабрики запущен.
      </ErrorState>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Нет связи с фабрикой');
    expect(screen.getByText('503 /api/version').closest('details')!.open).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('«скоро» называет версию; статус-метка несёт смысл', () => {
    render(
      <>
        <Soon version="0.2" title="Каналы">
          Список каналов появится с API каналов.
        </Soon>
        <StatusBadge tone="warn">холд</StatusBadge>
      </>,
    );
    expect(screen.getByText('Скоро · версия 0.2')).toBeInTheDocument();
    expect(screen.getByText('холд')).toHaveAttribute('data-tone', 'warn');
  });
});
