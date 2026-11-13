// Карточка публикации без оператора (CC-0127; фабрика CF-0747/CF-0748, договор 0.56.0): у каждой
// карточки — состояние `card {state, state_ru, placeable, why, reasons, ruling, build}` (none /
// building / ready / ruled — принята решением пользователя / not_ready). Готовность для
// размещения — `placeable` (ready или ruled), не `ready`: у `StashCard.ready` строгий смысл, у
// ruled он false. Сведения — `GET /api/publish/{c}/cards/{slug}?batch_id=` (`CardInfo`).
// Записи — в два шага, как остальные записи публикации: «Собрать заново» (`…/cards/{slug}/build/
// plan {batch_id?, draft?}` → `…/build {confirm}` → `CardBuildStarted {run_id, result_url,
// poll_s}`) и опрос итога `GET /api/publish/{c}/cards/build/{run_id}` раз в `poll_s`, пока не
// `done` (`CardBuildOutcome.text_ru` — строка центра); «Принять своим решением» (`…/ruling/plan
// {batch_id?, words}` → `failing[]`, `scope` → `…/ruling {confirm}`; API коммитит `touched`).
// Отказы — `CardCenterProblem {message, code, details}`: сообщение уже по-русски, заголовок по
// коду — `cardProblemText`.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { NAMESAKES_TEXT, takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { publishKeys } from './publish';
import { videoKeys } from './videos';

export type CardState = Schemas['CardState'];
export type CardStateCode = CardState['state'];
export type CardInfo = Schemas['CardInfo'];
export type CardBuildRun = Schemas['CardBuildRun'];
export type CardBuildLaunchPlan = Schemas['CardBuildLaunchPlan'];
export type CardBuildStarted = Schemas['CardBuildStarted'];
export type CardBuildOutcome = Schemas['CardBuildOutcome'];
export type CardRulingPlan = Schemas['CardRulingPlan'];
export type CardRulingResult = Schemas['CardRulingResult'];
export type CardFailing = Schemas['CardFailing'];
export type CardCenterProblem = Schemas['CardCenterProblem'];
export type CardCenterRefusal = Schemas['CardCenterRefusal'];
export type AcceptCardBuild = Schemas['AcceptCardBuild'];
/** Состояние, как его знает любая карточка (у `StashCard` поля со значением по умолчанию). */
export type CardStateLike = Pick<CardState, 'state'> &
  Partial<Pick<CardState, 'state_ru' | 'placeable' | 'why' | 'reasons' | 'ruling' | 'build'>>;

/** Слова решения пользователя: от 1 до 1000 знаков (договор `CardRulingPlanIn.words`). */
export const RULING_MAX = 1000;
/** Опрос сборки, если API не назвал `poll_s`. */
export const BUILD_POLL_S = 5;

export const cardKeys = {
  all: [...publishKeys.all, 'cards'] as const,
  info: (c: string, slug: string, batchId: string | null) =>
    [...publishKeys.all, 'cards', 'info', c, slug, batchId ?? ''] as const,
  run: (c: string, runId: string) => [...publishKeys.all, 'cards', 'run', c, runId] as const,
};

const card = (channel: string, slug: string) => ({ path: { channel, slug } });

export async function getCardInfo(
  channel: string,
  slug: string,
  batchId: string | null,
  signal?: AbortSignal,
): Promise<CardInfo> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/cards/{slug}', {
      params: { ...card(channel, slug), query: batchId ? { batch_id: batchId } : {} },
      signal,
    }),
  );
}

export async function getCardBuildResult(
  channel: string,
  runId: string,
  signal?: AbortSignal,
): Promise<CardBuildOutcome> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/cards/build/{run_id}', {
      params: { path: { channel, run_id: runId } },
      signal,
    }),
  );
}

const call = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

export type CardBuildBody = { batch_id: string | null };
export type CardRulingBody = { batch_id: string | null; words: string };

/** План «Собрать заново»: что сборка сделает и что станет с карточкой (решение пропадёт). */
export const planCardBuild = (channel: string, slug: string, body: CardBuildBody) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/cards/{slug}/build/plan', {
        params: card(channel, slug),
        body,
        signal,
      }),
    ),
  );

export const cardBuild = (channel: string, slug: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/cards/{slug}/build', {
        params: card(channel, slug),
        body: { confirm },
        signal,
      }),
    ),
  );

/** План «Принять своим решением»: что не прошло (`failing[]`) и что решение покрывает. */
export const planCardRuling = (channel: string, slug: string, body: CardRulingBody) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/cards/{slug}/ruling/plan', {
        params: card(channel, slug),
        body,
        signal,
      }),
    ),
  );

export const cardRuling = (channel: string, slug: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/cards/{slug}/ruling', {
        params: card(channel, slug),
        body: { confirm },
        signal,
      }),
    ),
  );

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Сведения о карточке ролика; пока она собирается — перечитываются раз в `BUILD_POLL_S`. */
export function useCardInfo(
  channel: string | null,
  slug: string,
  batchId: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: cardKeys.info(channel ?? '', slug, batchId),
    queryFn: ({ signal }) => getCardInfo(channel!, slug, batchId, signal),
    enabled: enabled && !!channel,
    staleTime: 30_000,
    refetchInterval: (q) => (q.state.data?.state === 'building' ? BUILD_POLL_S * 1000 : false),
    retry,
  });
}

/** Чтения публикации, где видно состояние карточки (перечитываются по итогу сборки). */
const CARD_VIEWS: ReadonlySet<string> = new Set(['stash', 'cards', 'queue', 'note', 'overview']);

/**
 * Что перечитать по итогу сборки карточки ролика `slug` канала `channel`: виды публикации, где
 * видно состояние карточки, и ролики. Карточка дня (`note`) — только этого ролика: чужие
 * карточки сборка не меняет, а их перечитывание по прежнему «день/ролик» сразу после переноса
 * в ленте (лента ещё не перечитана) — 404 на каждый перенесённый ролик (CC-0178). Ролик не
 * назван — как раньше, все карточки дней.
 */
export function staleAfterBuild(
  channel: string | null | undefined,
  slug: string | null | undefined,
): (key: readonly unknown[]) => boolean {
  return (k) => {
    // Сам итог сборки не перечитываем — он уже окончательный.
    if (k[2] === 'cards' && k[3] === 'run') return false;
    // Только то, где видно состояние карточки: холды, пауза, ротация и прочее сборка не
    // трогает — их перечитывание посреди чужого действия (подпись холда) только мешает.
    if (k[0] === publishKeys.all[0] && k[1] === publishKeys.all[1]) {
      if (k[2] === 'note' && slug) return k[3] === channel && k[4] === slug;
      return CARD_VIEWS.has(String(k[2]));
    }
    return k[0] === videoKeys.all[0] && k[1] === videoKeys.all[1];
  };
}

/**
 * Опрос сборки `run_id` раз в `poll_s` (из ответа «да» или итога), пока не `done`. Сборка
 * закончилась — всё про публикацию и ролики перечитывается один раз: состояние карточки сменилось.
 */
export function useCardBuildRun(
  channel: string | null,
  runId: string | null,
  pollS?: number | null,
) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: cardKeys.run(channel ?? '', runId ?? ''),
    queryFn: ({ signal }) => getCardBuildResult(channel!, runId!, signal),
    enabled: !!channel && !!runId,
    refetchInterval: (query) =>
      query.state.data?.done
        ? false
        : Math.max(1, query.state.data?.poll_s ?? pollS ?? BUILD_POLL_S) * 1000,
    refetchIntervalInBackground: true,
    retry,
  });
  const done = !!q.data?.done;
  const builtChannel = q.data?.channel ?? channel;
  const builtSlug = q.data?.slug ?? null;
  useEffect(() => {
    if (!done) return;
    const stale = staleAfterBuild(builtChannel, builtSlug);
    void qc.invalidateQueries({ predicate: (x) => stale(x.queryKey) });
  }, [done, qc, builtChannel, builtSlug]);
  return q;
}

/** Что сборке/решению сказать словами по коду отказа (сообщение API — под заголовком). */
export const CARD_PROBLEM_TEXT: Record<string, string> = {
  not_working_factory: 'Только смотреть: записи делает только API на рабочей фабрике',
  bad_who: 'Не записано, кто это делает',
  unknown_channel: 'Такого канала нет',
  batch_missing: 'Батча ролика нет на диске',
  unknown_video: 'Такого ролика в батче нет',
  bad_draft: 'Черновик карточки не годится',
  running: 'Карточка уже собирается — дождитесь итога',
  spawn_failed: 'Фабрика не смогла запустить сборку',
  batch_required: 'Нужно назвать батч ролика',
  namesakes: NAMESAKES_TEXT,
  bad_words: 'Решение — от 1 до 1000 знаков вашими словами',
  not_accepted: 'Ролик не принят — решение по карточке дают только принятому',
  building: 'Карточка ещё собирается — решение можно дать, когда сборка закончится',
  no_card: 'У ролика нет карточки',
  card_ready: 'Карточка уже готова — решение не нужно',
  claims_not_failed: 'Проверка утверждений не провалена — решать нечего',
  failing_unknown: 'Фабрика не смогла назвать, что не прошло',
  note_claim_failed:
    'Не прошло утверждение карточки (название или описание), а не слова ролика — это решением не принять, карточку надо собрать заново',
  card_problem: 'С карточкой что-то не так — посмотрите подробности',
  no_video: 'Ролика нет',
  check_changed: 'С момента плана карточка изменилась — посмотрите план заново',
  place_failed: 'Фабрика не смогла положить карточку',
  not_repo: 'Корень фабрики — не git-репозиторий: коммитить некуда',
  dirty: 'В папке публикации есть незакоммиченные правки — сначала их надо закоммитить',
  commit_refused: 'Записано, но коммит не прошёл — правки остались незакоммиченными',
  invalid: 'Фабрика не приняла запрос',
  busy: 'Идёт другая запись публикации — подождите и нажмите ещё раз',
  confirm_unknown: 'Подтверждение не найдено или уже использовано — нужен новый план',
  confirm_channel: 'Подтверждение выдано для другого канала — нужен новый план',
  confirm_expired: 'План устарел — запросите заново: подтверждение живёт две минуты',
  confirm_mismatch: 'Подтверждение было выдано другому действию и сгорело — нужен новый план',
  factory_broken:
    'Фабрика сломалась посреди записи — сначала посмотрите состояние, потом повторяйте',
  bad_run: 'Номер сборки не годится',
  unknown_run: 'Такой сборки фабрика не знает',
};

export const cardProblemText = (code: string | null | undefined): string =>
  (code && CARD_PROBLEM_TEXT[code]) || 'Фабрика отказала';
