// Процесс cc-api (CC-0155, договор 0.70.0): `GET /api/version` говорит, когда запущен процесс API
// (`started_at`), на каком коммите корня (`commit_at_start`) и не отстал ли он от кода фабрики
// (`stale`: с запуска изменились `*.py` или `agents.lock.json` — нужен перезапуск; null — сверить
// не удалось). Здесь — слова для человека; коммиты и пути — только под «Подробнее».
import type { Version } from '@/api/client';
import { dateTimeMsk } from '@/pages/batches/format';

export type ApiProcessFields = Pick<
  Version,
  'started_at' | 'commit_at_start' | 'stale' | 'stale_paths'
> & { factory: Pick<Version['factory'], 'commit'> };

/**
 * `stale` — API на старом коде, `fresh` — на том же, что у фабрики, `unknown` — сверить не
 * удалось; null — API старше договора 0.70.0 и о процессе не говорит ничего.
 */
export type ApiFreshness = 'fresh' | 'stale' | 'unknown';

export const STALE_TITLE = 'API работает на старом коде — с запуска изменился код фабрики.';
export const STALE_ACTION = 'Нужен перезапуск API (это делает фабрика).';
export const UNKNOWN_TEXT = 'не удалось сверить';
export const FRESH_TEXT = 'на текущем коде фабрики';

/** Короткий коммит, как его пишет git: 7 знаков. */
export const shortCommit = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : null);

/** Что сказать о процессе API; null — полей процесса в ответе нет (API до 0.70.0). */
export function apiFreshness(v: Partial<ApiProcessFields>): ApiFreshness | null {
  if (v.stale === true) return 'stale';
  if (v.stale === false) return 'fresh';
  if (v.stale === null || v.started_at || v.commit_at_start) return 'unknown';
  return null;
}

/**
 * «API запущен 22.10, 01:15 МСК · на коммите abc1234». `commit: false` — без коммита (на виду:
 * коммит — только под «Подробнее»). Нет ни времени, ни коммита — null.
 */
export function apiStartedText(
  v: Partial<Pick<ApiProcessFields, 'started_at' | 'commit_at_start'>>,
  { commit = true }: { commit?: boolean } = {},
): string | null {
  const at = dateTimeMsk(v.started_at);
  const sha = shortCommit(v.commit_at_start);
  if (!at && !sha) return null;
  const head = at ? `API запущен ${at} МСК` : 'API запущен';
  return commit && sha ? `${head} · на коммите ${sha}` : head;
}

/** Подсказка пилюли в шапке, когда API на старом коде. */
export const STALE_TIP = `${STALE_TITLE} ${STALE_ACTION} Что изменилось — на экране «Версии», под «Подробнее».`;
