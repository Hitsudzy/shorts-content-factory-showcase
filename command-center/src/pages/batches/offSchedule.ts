// Каналы вне расписания батчей (CC-0140): план фабрики берёт только каналы в расписании, о
// прочих молчит в днях — выглядит, будто канала нет. Здесь — строка на каждый такой канал и
// причина словами из того, что центр уже читает: план (`GET /api/schedule` `channels`),
// список каналов (`GET /api/channels`: `error`, `no_pipeline`) и очереди публикаций
// (`GET /api/publish`: в ней каналы со слотом, `slot: null` — слота нет). Своей логики
// фабрики не придумываем: нет причины ни в одном ответе — «вне расписания батчей» и ссылка
// на окно канала.
import type { ChannelSummary } from '@/api/channels';
import type { PublishOverview } from '@/api/publish';
import type { SchedulePlan } from '@/api/schedule';

export type OffReason = 'config_error' | 'no_pipeline' | 'no_slot' | 'disabled' | 'unknown';

/** Причина для человека — порядок проверок как у плана фабрики (`_channel_state`). */
export const OFF_REASON_TEXT: Record<OffReason, string> = {
  config_error: 'настройки канала не читаются',
  no_pipeline: 'у канала нет конвейера',
  no_slot: 'нет слота публикации',
  disabled: 'расписание батчей канала выключено',
  unknown: 'вне расписания батчей',
};

export type OffChannel = {
  id: string;
  reason: OffReason;
  /** Строка плана фабрики «почему не берёт», как есть (под «подробнее»). */
  factory: string | null;
  /** У канала есть карточка «Окна каналов» на этой же странице. */
  hasWindow: boolean;
};

const has = (c: ChannelSummary, id: string) => c.id === id || c.former_ids.includes(id);

/** Почему канал вне расписания — по данным плана, списка каналов и очередей публикаций. */
export function offReason(
  id: string,
  plan: SchedulePlan,
  channels: readonly ChannelSummary[] | undefined,
  publish: PublishOverview | undefined,
): OffReason {
  const p = plan.channels[id];
  const c = channels?.find((x) => has(x, id));
  if (c?.error || p?.settings.error) return 'config_error';
  // План сам говорит, есть ли конвейер; список каналов — только если в плане канала нет.
  if (p ? p.no_pipeline : c?.no_pipeline) return 'no_pipeline';
  if (publish) {
    const line = publish.channels.find((q) => q.channel === id);
    // В очередях — каналы со слотом (и со сломанным блоком: у них `error`, о слоте не знаем).
    if (line ? line.slot == null && !line.error : true) return 'no_slot';
  }
  if (p?.settings.enabled === false) return 'disabled';
  return 'unknown';
}

/**
 * Каналы, которые план не берёт: `plannable: false` в плане или канала в плане нет вовсе
 * (а фабрика его знает — он есть в списке каналов). Порядок — как в списке каналов.
 */
export function offSchedule(
  plan: SchedulePlan,
  channels: readonly ChannelSummary[] | undefined,
  publish: PublishOverview | undefined,
): OffChannel[] {
  const ids = [...Object.keys(plan.channels)];
  for (const c of channels ?? []) {
    if (!ids.some((id) => has(c, id))) ids.push(c.id);
  }
  const order = (id: string) => {
    const i = channels?.findIndex((c) => has(c, id)) ?? -1;
    return i < 0 ? Number.MAX_SAFE_INTEGER : i;
  };
  return ids
    .filter((id) => !plan.channels[id]?.plannable)
    .sort((a, b) => order(a) - order(b))
    .map((id) => ({
      id,
      reason: offReason(id, plan, channels, publish),
      factory: plan.channels[id]?.why_not ?? null,
      hasWindow: id in plan.channels,
    }));
}
