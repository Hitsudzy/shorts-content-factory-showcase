// CC-0162: общий хук записи параметров адреса — от текущего адреса роутера, а не от
// отрисованного. Под нагрузкой второй щелчок приходит раньше перерисовки после первого.
import { act, render } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router';

import { useLiveSearchParams, type SetSearch } from './useLiveSearchParams';

type Seen = { params: URLSearchParams; set: SetSearch };

function Probe({ seen }: { seen: Seen[] }) {
  const [params, set] = useLiveSearchParams();
  seen.push({ params, set });
  return null;
}

function setup(path: string) {
  const seen: Seen[] = [];
  const router = createMemoryRouter([{ path: '/x', element: <Probe seen={seen} /> }], {
    initialEntries: [path],
  });
  render(<RouterProvider router={router} />);
  return { router, seen, first: seen[0]! };
}

const put = (key: string, value: string) => (p: URLSearchParams) => {
  if (value) p.set(key, value);
  else p.delete(key);
  return p;
};

it('изменения подряд от одной отрисовки не стирают друг друга', () => {
  const { router, first } = setup('/x?view=a&q=tech');
  // Все — от первого рендера, как щелчки до перерисовки.
  act(() => {
    first.set(put('q', ''));
    first.set(put('source', 'trend-hunter'));
    first.set(put('channel', 'example-film'));
  });
  expect(router.state.location.search).toBe('?view=a&source=trend-hunter&channel=example-film');
});

it('по умолчанию — с заменой шага истории; push — когда попросили', () => {
  const { router, seen } = setup('/x');
  act(() => seen.at(-1)!.set(put('a', '1')));
  expect(router.state.historyAction).toBe('REPLACE');
  act(() => seen.at(-1)!.set(put('b', '2'), { replace: false }));
  expect(router.state.historyAction).toBe('PUSH');
  expect(router.state.location.search).toBe('?a=1&b=2');
});

it('функция получает копию: отрисованные параметры она не меняет', () => {
  const { first } = setup('/x?a=1');
  act(() =>
    first.set((p) => {
      p.set('a', '2');
      return p;
    }),
  );
  expect(first.params.get('a')).toBe('1');
});

it('отрисовка — с новыми параметрами', () => {
  const { seen } = setup('/x?a=1');
  act(() => seen.at(-1)!.set(put('a', '2')));
  expect(seen.at(-1)!.params.get('a')).toBe('2');
});

it('без data-роутера — от отрисованных параметров', () => {
  const seen: Seen[] = [];
  render(
    <MemoryRouter initialEntries={['/x?a=1']}>
      <Probe seen={seen} />
    </MemoryRouter>,
  );
  act(() => seen.at(-1)!.set(put('b', '2')));
  expect(seen.at(-1)!.params.toString()).toBe('a=1&b=2');
});
