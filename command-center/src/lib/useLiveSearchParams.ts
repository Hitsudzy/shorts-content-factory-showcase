// Параметры адреса и запись их обратно — от текущего адреса роутера, а не от отрисованного
// (CC-0159 в «Разработке», общим хуком — CC-0162).
import { useContext } from 'react';
import { UNSAFE_DataRouterContext, useSearchParams, type NavigateOptions } from 'react-router';

/** Изменение параметров адреса: получает копию текущих (её можно менять) и отдаёт новые. */
export type SearchUpdate = (cur: URLSearchParams) => URLSearchParams;

/** Запись параметров: по умолчанию с заменой шага истории (без лишних шагов «назад»). */
export type SetSearch = (update: SearchUpdate, options?: NavigateOptions) => void;

/**
 * Как `useSearchParams`, но запись — только функцией от текущего адреса.
 *
 * react-router перерисовывает экран в `startTransition`, и под нагрузкой второй щелчок по
 * фильтру приходит раньше, чем отрисован первый. И отрисованные параметры, и функция в
 * `setSearchParams` (роутер отдаёт в неё параметры последней отрисовки) тогда ещё старые —
 * запись по ним стирает только что выбранное. `router.state` обновляется сразу, до
 * перерисовки, поэтому изменение применяется к нему. Без data-роутера — к отрисованным.
 */
export function useLiveSearchParams(): [URLSearchParams, SetSearch] {
  const [params, setParams] = useSearchParams();
  const router = useContext(UNSAFE_DataRouterContext)?.router;
  const set: SetSearch = (update, options = { replace: true }) => {
    const live = new URLSearchParams(router ? router.state.location.search : params);
    setParams(update(live), options);
  };
  return [params, set];
}
