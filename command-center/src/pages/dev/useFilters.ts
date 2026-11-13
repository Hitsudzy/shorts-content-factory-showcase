// Фильтры «Разработки» из адреса и запись их обратно (CC-0124) — с заменой шага истории.
import { useMemo } from 'react';

import { useLiveSearchParams } from '@/lib/useLiveSearchParams';

import { filtersToParams, parseFilters, type DevFilters } from './filters';

/** Изменение фильтров — от текущих, а не от отрисованных. */
export type FiltersUpdate = (cur: DevFilters) => DevFilters;

/**
 * Фильтры из адреса и запись их обратно (с заменой, без лишних шагов «назад»).
 *
 * CC-0159: под нагрузкой второй щелчок (проект → статус → веха подряд) приходит раньше, чем
 * отрисован первый, и запись по фильтрам из замыкания стирала только что выбранное. Поэтому
 * изменение — функцией от текущего адреса роутера (общий хук `useLiveSearchParams`, CC-0162).
 */
export function useFilters(): [DevFilters, (update: FiltersUpdate) => void] {
  const [params, setParams] = useLiveSearchParams();
  const f = useMemo(() => parseFilters(params), [params]);
  const set = (update: FiltersUpdate) =>
    setParams((live) => filtersToParams(update(parseFilters(live)), live));
  return [f, set];
}
