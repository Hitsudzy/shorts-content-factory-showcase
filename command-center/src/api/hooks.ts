// Хуки TanStack Query поверх клиента (CC-0004). Ключи — здесь же, чтобы инвалидировать
// одним местом.
import { useQuery } from '@tanstack/react-query';

import { getHealth, getSession, getVersion } from './client';

export const apiKeys = {
  health: ['api', 'health'] as const,
  version: ['api', 'version'] as const,
  session: ['api', 'session'] as const,
};

/**
 * Жив ли API и пишет ли он (CC-0059: `writes`, см. ./writes). Без повторов: бейдж сразу
 * показывает «нет связи». Один запрос на всё приложение; перечитывается при фокусе вкладки.
 */
export function useHealth() {
  return useQuery({
    queryKey: apiKeys.health,
    queryFn: ({ signal }) => getHealth(signal),
    retry: false,
    refetchOnWindowFocus: true,
  });
}

/** Версия фабрики, пины агентов, сборка центра. */
export function useVersion() {
  return useQuery({
    queryKey: apiKeys.version,
    queryFn: ({ signal }) => getVersion(signal),
  });
}

/** Токен сессии (для будущих действий); сам клиент вешает его на POST и без хука. */
export function useSession() {
  return useQuery({
    queryKey: apiKeys.session,
    queryFn: () => getSession(),
    staleTime: Infinity,
  });
}
