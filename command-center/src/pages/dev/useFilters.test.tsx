// CC-0159: запись фильтров — от текущего адреса роутера, а не от отрисованных фильтров.
// Под нагрузкой второй щелчок приходит раньше перерисовки после первого; раньше он писал
// адрес по старым фильтрам и стирал только что выбранное.
import { act, render } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

import { toggle, type DevFilters } from './filters';
import { useFilters, type FiltersUpdate } from './useFilters';

function setup(path: string) {
  const seen: { f: DevFilters; set: (u: FiltersUpdate) => void }[] = [];
  function Probe() {
    const [f, set] = useFilters();
    seen.push({ f, set });
    return null;
  }
  const router = createMemoryRouter([{ path: '/dev', element: <Probe /> }], {
    initialEntries: [path],
  });
  render(<RouterProvider router={router} />);
  return { router, first: seen[0]! };
}

it('щелчки подряд по одним и тем же отрисованным фильтрам не стирают друг друга', () => {
  const { router, first } = setup('/dev?view=roadmap&q=tech');
  // Все три — от одного и того же (первого) рендера, как при щелчках до перерисовки.
  act(() => {
    first.set((cur) => ({ ...cur, q: '' }));
    first.set((cur) => ({ ...cur, project: ['center'] }));
    first.set((cur) => toggle(cur, 'status', 'in-progress'));
    first.set((cur) => toggle(cur, 'status', 'blocked'));
    first.set((cur) => toggle(cur, 'status', 'blocked'));
  });
  expect(router.state.location.search).toBe('?view=roadmap&project=center&status=in-progress');
});
