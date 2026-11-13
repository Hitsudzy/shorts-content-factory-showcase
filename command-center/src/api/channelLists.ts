// Правка списков канала и сборка концовки (CC-0114 API, CC-0115 шаг 3 центра). Списки —
// источники фактов, происхождение футажа, партнёрские ссылки (весь документ `doc`): план
// `…/plan {doc, base_sha256}` ничего не пишет, `base_sha256` — `sha256` чтения, с которого начата
// правка (другой — `check_changed`: «Список изменился, откройте заново»); «да» — `{confirm}`,
// фабрика сама сохраняет файл в своей истории. Концовка — `…/ending/plan` (без тела: план
// фабрики заново, открытые батчи канала) → `…/ending {confirm}`: рендер запускается отдельно и
// отвечает сразу (pid, журнал).
import { useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { channelDataKeys } from './channelData';
import { api, type Schemas } from './client';
import { writeProblemText } from './publishWrites';
import { rightsKeys } from './rights';

export type ChannelListPlan = Schemas['ChannelListPlan'];
export type ChannelListWriteResult = Schemas['ChannelListWriteResult'];
export type EndingRenderPlan = Schemas['EndingRenderPlan'];
export type EndingRenderResult = Schemas['EndingRenderResult'];

/** Какой список правим. */
export type ListKind = 'fact-sources' | 'footage-origin' | 'affiliate';

/** Что уходит в план: весь документ. */
export type ListPayload = {
  value: Record<string, unknown>;
  base_sha256: string | null;
};

const writeCall = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);
const ch = (channel: string) => ({ path: { channel } });

type Doc = Record<string, unknown>;

export const planList = (channel: string, kind: ListKind, p: ListPayload) =>
  writeCall(async (signal): Promise<ChannelListPlan> => {
    const params = ch(channel);
    const doc = { doc: p.value as Doc, base_sha256: p.base_sha256 };
    switch (kind) {
      case 'fact-sources':
        return takeBatch(
          await api.POST('/api/channels/{channel}/fact-sources/plan', {
            params,
            body: doc,
            signal,
          }),
        );
      case 'footage-origin':
        return takeBatch(
          await api.POST('/api/channels/{channel}/footage-origin/plan', {
            params,
            body: doc,
            signal,
          }),
        );
      case 'affiliate':
        return takeBatch(
          await api.POST('/api/channels/{channel}/affiliate/plan', { params, body: doc, signal }),
        );
    }
  });

export const writeList = (channel: string, kind: ListKind, confirm: string) =>
  writeCall(async (signal): Promise<ChannelListWriteResult> => {
    const params = ch(channel);
    const body = { confirm };
    switch (kind) {
      case 'fact-sources':
        return takeBatch(
          await api.POST('/api/channels/{channel}/fact-sources', { params, body, signal }),
        );
      case 'footage-origin':
        return takeBatch(
          await api.POST('/api/channels/{channel}/footage-origin', { params, body, signal }),
        );
      case 'affiliate':
        return takeBatch(
          await api.POST('/api/channels/{channel}/affiliate', { params, body, signal }),
        );
    }
  });

export const planEnding = (channel: string) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/channels/{channel}/ending/plan', { params: ch(channel), signal }),
    ),
  );

export const renderEnding = (channel: string, confirm: string) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/channels/{channel}/ending', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

/** После правки списка или запуска концовки (и отказа «да») — перечитать данные канала и списки. */
export function useAfterChannelListWrite(channel: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: channelDataKeys.ending(channel) });
    void qc.invalidateQueries({ queryKey: channelDataKeys.factSources(channel) });
    void qc.invalidateQueries({ queryKey: channelDataKeys.affiliate(channel) });
    void qc.invalidateQueries({ queryKey: rightsKeys.all });
  };
}

/** Сменившийся список — словами экрана. */
export const LIST_CHANGED = 'Список изменился, откройте заново';

const LIST_PROBLEM_TEXT: Record<string, string> = {
  check_changed: LIST_CHANGED,
  invalid: 'Список не прошёл проверку фабрики — поправьте его',
  batch_open: 'Идёт батч канала — списки не пишутся до его конца',
  locked: 'Список сейчас пишет кто-то другой — подождите и повторите',
  busy: 'Идёт другая запись списка — подождите и нажмите ещё раз',
  not_repo: 'Список не сохранить в истории фабрики — ничего не записано',
  commit_refused: 'История фабрики не приняла запись списка — файл возвращён как был',
  write_failed: 'Список не записался',
  unknown_channel: 'Такого канала нет',
  unknown_list: 'Такого списка у канала нет',
  // Концовка.
  render_running: 'Концовка уже собирается — дождитесь конца',
  start_failed: 'Рендер концовки не запустился',
  ending_by_hand: 'Концовка собрана вручную — пересобирать её не из чего',
  ending_no_generator: 'Генератор не умеет концовку этого канала',
  ending_file_missing: 'Для концовки не хватает файла',
  ending_sha256_mismatch: 'Клип концовки не тот, что записан в данных канала',
  ending_invalid: 'Данные концовки в бренде канала не читаются',
  ending_args_missing: 'В данных канала нет всего, что нужно для концовки',
  plan_broken: 'Фабрика не составила план концовки',
  factory_broken: 'Фабрика ответила ошибкой — посмотрите данные канала, прежде чем повторять',
};

export const listProblemText = (code: string | null | undefined): string =>
  (code && LIST_PROBLEM_TEXT[code]) || writeProblemText(code);
