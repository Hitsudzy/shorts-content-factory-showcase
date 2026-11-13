// Версии и агенты (CC-0030 фабрики, договор 0.33.0; выпуск и «в работе» — CC-0119, 0.46.0;
// экран — CC-0031). Одно чтение `GET /api/versions`: что фабрика говорит о своей копии — версия
// README, выпуск на `main` (`release_tag`), ветки выпусков с живой рабочей копией
// (`versions_in_work`), агенты и модули против `agents.lock.json` (пин, коммит пина, HEAD, ветка,
// изменённые файлы, ok / why) и строки `scripts/agents status` как есть, версия центра. Проверка
// ходит git по всем агентам (секунды), поэтому API держит ответ `ttl_s`; `?fresh=true` — проверить
// заново.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap, type Schemas } from './client';

export type Versions = Schemas['Versions'];
export type AgentState = Schemas['AgentState'];
export type ModuleState = Schemas['ModuleState'];
export type StatusLine = Schemas['StatusLine'];

export const versionsKeys = {
  all: ['versions'] as const,
};

export async function getVersions(fresh = false, signal?: AbortSignal): Promise<Versions> {
  return unwrap(
    await api.GET('/api/versions', { params: { query: fresh ? { fresh: true } : {} }, signal }),
  );
}

/** Сохранённый ответ фабрики (её `ttl_s` — 30 с): без опроса, перечитывается при возврате на вкладку. */
export function useVersions() {
  return useQuery({
    queryKey: versionsKeys.all,
    queryFn: ({ signal }) => getVersions(false, signal),
    staleTime: 30_000,
  });
}

/** «Проверить заново»: свежая проверка (`?fresh=true`) кладётся на место ответа. */
export function useRecheck() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => getVersions(true),
    onSuccess: (v) => qc.setQueryData(versionsKeys.all, v),
  });
}
