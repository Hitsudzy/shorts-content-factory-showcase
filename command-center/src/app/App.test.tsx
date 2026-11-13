import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { fixtures } from '@/mocks/fixtures';
import { mockGet } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { AREAS } from './areas';

describe('каркас приложения', () => {
  it('показывает 13 табов и статус API из подставного сервера', async () => {
    renderApp();

    const nav = screen.getByRole('navigation', { name: 'Разделы' });
    const tabs = within(nav).getAllByRole('link');
    expect(tabs).toHaveLength(13);
    expect(tabs.map((t) => t.textContent)).toEqual(AREAS.map((a) => a.short));

    expect(await screen.findByText('Фабрика на связи')).toBeInTheDocument();
    expect(screen.getByTestId('api-status')).toHaveTextContent('Фабрика на связи');
    expect(screen.getByRole('heading', { name: 'Главная', level: 1 })).toBeInTheDocument();
  });

  it('переходит в раздел по клику на таб; заглушек «скоро» больше нет (CC-0033)', async () => {
    renderApp();
    await userEvent.click(screen.getByRole('link', { name: 'Обслуживание' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Обслуживание и расход' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Скоро · версия/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Обслуживание' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(AREAS.filter((a) => a.soon)).toEqual([]);
  });

  it('показывает «нет связи», когда API отвечает ошибкой', async () => {
    server.use(http.get('*/api/health', () => new HttpResponse(null, { status: 503 })));
    renderApp('/batches');
    expect(await screen.findByText('Нет связи с фабрикой')).toBeInTheDocument();
  });

  it('говорит, когда сервер на другом контракте, чем собран центр', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, api: '9.9.9' }));
    renderApp();
    expect(await screen.findByText('Другой договор API')).toBeInTheDocument();
  });

  it('не пускает в сеть запросы мимо подставного API', async () => {
    await expect(fetch('https://example.com/')).rejects.toThrow();
  });
});
