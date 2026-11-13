// Расписание батчей (CC-0044 фабрики): план на N дней, рубильник с заметкой, окна каналов.
// Рубильник и окна — состояние расписания фабрики (`schedule/`, вне git): идущий батч их
// не блокирует. Отказы — `BatchError` (./batchProblem), `message` показывается как есть.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { takeBatch } from './batchProblem';
import { api, type Schemas } from './client';

export type SchedulePlan = Schemas['SchedulePlan'];
export type PlanDay = Schemas['PlanDay'];
export type PlanChannel = Schemas['PlanChannel'];
export type Switch = Schemas['Switch'];
export type SwitchRow = Schemas['SwitchRow'];
export type SwitchIn = Schemas['SwitchIn'];
export type ScheduleSettings = Schemas['ScheduleSettings'];
export type ScheduleSettingsEdit = Schemas['ScheduleSettingsEdit'];
export type ChannelSchedule = Schemas['ChannelSchedule'];
export type SettingsResult = Schemas['SettingsResult'];
export type SettingsRow = Schemas['SettingsRow'];

/** Дней в плане экрана «Батчи». */
export const PLAN_DAYS = 7;

export async function getSchedule(days = PLAN_DAYS, signal?: AbortSignal): Promise<SchedulePlan> {
  return takeBatch(await api.GET('/api/schedule', { params: { query: { days } }, signal }));
}

/** Рубильник: включить — только с заметкой (где и когда сказано «включай»), иначе 422. */
export async function setSwitch(body: SwitchIn): Promise<Switch> {
  return takeBatch(await api.POST('/api/schedule/switch', { body }));
}

const path = (channel: string) => ({ params: { path: { channel } } });

export async function getChannelSchedule(
  channel: string,
  signal?: AbortSignal,
): Promise<ChannelSchedule> {
  return takeBatch(await api.GET('/api/schedule/channels/{channel}', { ...path(channel), signal }));
}

/** Окно канала. `changed: {}` в ответе — ничего не поменялось, строка истории не записана. */
export async function saveChannelSchedule(
  channel: string,
  body: ScheduleSettingsEdit,
): Promise<SettingsResult> {
  return takeBatch(await api.PUT('/api/schedule/channels/{channel}', { ...path(channel), body }));
}

export const scheduleKeys = {
  all: ['api', 'schedule'] as const,
  plan: (days: number) => ['api', 'schedule', 'plan', days] as const,
  channel: (id: string) => ['api', 'schedule', 'channel', id] as const,
};

/** План раз в минуту: окна проходят, батчи открываются и закрываются. */
const PLAN_REFRESH_MS = 60_000;

export function useSchedule(days = PLAN_DAYS) {
  return useQuery({
    queryKey: scheduleKeys.plan(days),
    queryFn: ({ signal }) => getSchedule(days, signal),
    refetchInterval: PLAN_REFRESH_MS,
  });
}

export function useChannelSchedule(id: string) {
  return useQuery({
    queryKey: scheduleKeys.channel(id),
    queryFn: ({ signal }) => getChannelSchedule(id, signal),
    // Форма держит черновик: свежий ответ сам по себе её не перетирает (см. ChannelWindow).
    refetchOnWindowFocus: false,
  });
}

/** После записи план перечитать: от рубильника и окон зависят дни и `why`. */
function useReplan() {
  const qc = useQueryClient();
  return () =>
    qc.invalidateQueries({
      predicate: (q) => q.queryKey[0] === 'api' && q.queryKey[1] === 'schedule',
    });
}

export function useSetSwitch() {
  const replan = useReplan();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: setSwitch,
    onSuccess: (sw) => {
      qc.setQueriesData<SchedulePlan>({ queryKey: [...scheduleKeys.all, 'plan'] }, (p) =>
        p ? { ...p, switch: sw } : p,
      );
      void replan();
    },
  });
}

export function useSaveChannelSchedule(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ScheduleSettingsEdit) => saveChannelSchedule(id, body),
    onSuccess: (r) => {
      qc.setQueryData<ChannelSchedule>(scheduleKeys.channel(id), {
        channel: r.channel,
        settings: r.settings,
        history: r.history,
      });
      if (Object.keys(r.changed).length) {
        void qc.invalidateQueries({ queryKey: [...scheduleKeys.all, 'plan'] });
      }
    },
  });
}
