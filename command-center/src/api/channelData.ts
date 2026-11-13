// Данные канала — только чтение (CC-0101/0102 фабрики, CC-0115 центра): концовка канала
// (`GET /api/channels/{c}/ending`: есть ли клип, длина, формат, звук, можно ли пересобрать из
// бренда), источники фактов (`…/fact-sources`: издания по уровням, что брать с любого сайта,
// чего не брать, виды фактов, ошибки фабрики) и партнёрские ссылки (`…/affiliate`: переключатель,
// программы, товары). Правка списков и сборка концовки — записи plan → confirm, следующим шагом.
import { useQuery } from '@tanstack/react-query';

import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type ChannelEnding = Schemas['ChannelEnding'];
export type ChannelFactSources = Schemas['ChannelFactSources'];
export type ChannelAffiliate = Schemas['ChannelAffiliate'];

const path = (channel: string) => ({ params: { path: { channel } } });

export async function getEnding(channel: string, signal?: AbortSignal): Promise<ChannelEnding> {
  // `media_url` всегда null — генератор типов ответа его теряет; форма — из схемы.
  return takeBatch(
    await api.GET('/api/channels/{channel}/ending', { ...path(channel), signal }),
  ) as ChannelEnding;
}

export async function getFactSources(
  channel: string,
  signal?: AbortSignal,
): Promise<ChannelFactSources> {
  return takeBatch(
    await api.GET('/api/channels/{channel}/fact-sources', { ...path(channel), signal }),
  );
}

export async function getAffiliate(
  channel: string,
  signal?: AbortSignal,
): Promise<ChannelAffiliate> {
  return takeBatch(
    await api.GET('/api/channels/{channel}/affiliate', { ...path(channel), signal }),
  );
}

export const channelDataKeys = {
  ending: (c: string) => ['api', 'channels', c, 'ending'] as const,
  factSources: (c: string) => ['api', 'channels', c, 'fact-sources'] as const,
  affiliate: (c: string) => ['api', 'channels', c, 'affiliate'] as const,
};

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

export function useEnding(channel: string) {
  return useQuery({
    queryKey: channelDataKeys.ending(channel),
    queryFn: ({ signal }) => getEnding(channel, signal),
    retry,
  });
}

export function useFactSources(channel: string) {
  return useQuery({
    queryKey: channelDataKeys.factSources(channel),
    queryFn: ({ signal }) => getFactSources(channel, signal),
    retry,
  });
}

export function useAffiliate(channel: string) {
  return useQuery({
    queryKey: channelDataKeys.affiliate(channel),
    queryFn: ({ signal }) => getAffiliate(channel, signal),
    retry,
  });
}
