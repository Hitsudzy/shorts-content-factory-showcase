import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { channels } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

describe('мастер «Новый канал»', { timeout: 30_000 }, () => {
  it('ошибка фабрики под полем → исправление → шаги → создание + позиция → редактор', async () => {
    const user = userEvent.setup();
    renderApp('/channels/new');
    const id = await screen.findByLabelText('Идентификатор');
    await user.type(id, 'example-film');
    await user.type(screen.getByLabelText('Название'), 'ExampleFood');
    expect(await screen.findByText("Канал 'example-film' уже есть")).toBeInTheDocument();
    await user.clear(id);
    await user.type(id, 'example-food');
    expect(await screen.findByTestId('dry-run-ok')).toBeInTheDocument();
    expect(channels.writes).toEqual([]);

    await user.click(screen.getByRole('button', { name: /Далее: Тематика и позиция/ }));
    await user.type(
      screen.getByLabelText('Позиция в одну фразу (можно оставить пустой)'),
      'Food facts, checked.',
    );
    await user.click(screen.getByRole('button', { name: 'Шаг 6: Проверка' }));
    expect(screen.getByTestId('review-thesis')).toHaveTextContent('Food facts, checked.');
    await user.click(screen.getByRole('button', { name: /Далее: Создать/ }));
    expect(within(screen.getByTestId('todo')).getByText('Конвейер')).toBeInTheDocument();
    await user.click(screen.getByTestId('create'));

    expect(await screen.findByTestId('wizard-landing')).toHaveTextContent(
      'с вашей позицией, одной правкой',
    );
    // Один коммит: позиция — в самом создании, без PUT следом.
    await waitFor(() => expect(channels.writes.map((w) => w.kind)).toEqual(['create']));
    const made = channels.writes[0]!.body as { stance_text: string };
    expect(made.stance_text).toContain('"thesis": "Food facts, checked."');
    expect(made.stance_text).toContain('"channel_id": "example-food"');
  });

  it('фабрика не приняла позицию — ничего не создано, замечания на шаге с фразой', async () => {
    const line = {
      field: 'stance.channel_id',
      text: "stance.json.channel_id: must be 'example-food' (the channel it is the position of), got 'x'",
    };
    server.use(
      http.post('*/api/channels', async ({ request }) => {
        const body = (await request.clone().json()) as { dry_run?: boolean };
        if (body.dry_run) return undefined;
        return HttpResponse.json(
          {
            code: 'invalid',
            message: 'Фабрика не приняла новый канал: 1 ошибка проверки. Ничего не создано.',
            details: [line.text],
            errors: [line],
            batches: [],
          },
          { status: 422 },
        );
      }),
    );
    const user = userEvent.setup();
    renderApp('/channels/new');
    await user.type(await screen.findByLabelText('Идентификатор'), 'example-food');
    await user.type(screen.getByLabelText('Название'), 'ExampleFood');
    await screen.findByTestId('dry-run-ok');
    await user.click(screen.getByRole('button', { name: /Далее: Тематика и позиция/ }));
    await user.type(screen.getByLabelText('Позиция в одну фразу (можно оставить пустой)'), 'X.');
    await user.click(screen.getByRole('button', { name: 'Шаг 7: Создать' }));
    await user.click(screen.getByTestId('create'));
    const failed = await screen.findByTestId('stance-failed');
    expect(failed).toHaveTextContent('Ничего не создано');
    expect(screen.getByRole('heading', { name: 'Тематика и позиция' })).toBeInTheDocument();
  });

  it('id «new»: текст отказа — фабрики', async () => {
    const user = userEvent.setup();
    renderApp('/channels/new');
    await user.type(await screen.findByLabelText('Идентификатор'), 'new');
    await user.type(screen.getByLabelText('Название'), 'ExampleNew');
    expect(await screen.findByText("'new' - служебное имя, не канал")).toBeInTheDocument();
    expect(screen.queryByTestId('dry-run-ok')).toBeNull();
  });

  it('идёт батч — создать нельзя, объяснение на месте', async () => {
    channels.openBatch('Идёт батч канала example-film: пока не закончится, канал не создать.');
    const user = userEvent.setup();
    renderApp('/channels/new');
    expect(await screen.findByTestId('create-lock')).toHaveTextContent('канал не создать');
    await user.type(screen.getByLabelText('Идентификатор'), 'example-food');
    await user.type(screen.getByLabelText('Название'), 'ExampleFood');
    await screen.findByTestId('dry-run-ok');
    await user.click(screen.getByRole('button', { name: 'Шаг 7: Создать' }));
    const create = screen.getByTestId('create');
    expect(create).toHaveAttribute('aria-disabled', 'true');
    await user.click(create);
    expect(channels.writes).toEqual([]);
  });
});
