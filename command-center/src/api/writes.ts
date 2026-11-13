// CC-0059: пишет ли API — `writes`/`writes_reason`/`writes_dev` из `GET /api/health`
// (CC-0058 фабрики). Вне рабочей фабрики (рабочая копия разработки, не `main`) API только
// показывает: каждая запись — 409 `not_working_factory`. Центр гасит кнопки записи заранее
// (`WriteButton`) и показывает плашку «Только смотреть» в шапке.
import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { onReadOnlyRefusal, type Health } from './client';
import { apiKeys, useHealth } from './hooks';
import { FALLBACK_REASON } from './plainReason';

export { plainReason } from './plainReason';

export type Writes = {
  /** Можно писать. Пока health не пришёл (или API не отвечает) — не гасим: решает сервер. */
  allowed: boolean;
  /** Почему только смотреть — строка фабрики как есть; `null`, когда писать можно. */
  reason: string | null;
  /** Включён флаг разработки `CC_API_WRITES=dev`: пишет рабочая копия. */
  dev: boolean;
  /** Чем это рабочая копия, если пишет она по флагу разработки. */
  devReason: string | null;
};

const PREFIX = /^Только смотреть:\s*/;

export function writesOf(h: Health | undefined): Writes {
  if (!h || h.writes !== false) {
    return {
      allowed: true,
      reason: null,
      dev: !!h?.writes_dev,
      devReason: h?.writes_dev ? (h.writes_reason ?? null) : null,
    };
  }
  return {
    allowed: false,
    reason: h.writes_reason || FALLBACK_REASON,
    dev: false,
    devReason: null,
  };
}

/** Режим записи центра: общий запрос health, обновляется при возврате на вкладку. */
export function useWrites(): Writes {
  return writesOf(useHealth().data);
}

/** Подсказка погашенной кнопки записи. */
export const readOnlyTip = (reason: string) =>
  `Только смотреть: ${reason}. Записи делает только API на рабочей фабрике`;

/**
 * Отказ `not_working_factory` посреди сессии (ветка сменилась в пределах кэша API): сразу
 * гасим запись причиной из `message` и перечитываем health. Вешается один раз — в шапке.
 */
export function useWritesRefusalWatch() {
  const qc = useQueryClient();
  useEffect(
    () =>
      onReadOnlyRefusal((message) => {
        qc.setQueryData<Health>(apiKeys.health, (h) =>
          h
            ? {
                ...h,
                writes: false,
                writes_dev: false,
                writes_reason: message.replace(PREFIX, '') || h.writes_reason || FALLBACK_REASON,
              }
            : h,
        );
        void qc.invalidateQueries({ queryKey: apiKeys.health });
      }),
    [qc],
  );
}
