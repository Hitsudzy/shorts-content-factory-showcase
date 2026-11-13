// Ворота центра (CC-0037): пока этому браузеру нужен вход — экран входа и ни одного запроса к
// закрытому API (сессия, health, контракт, демо-сервер тренировки). Центр поднимается (`load`)
// только когда вход не нужен или выполнен; 401 `auth_required` посреди работы — снова вход,
// адрес страницы не трогаем: после входа центр монтируется на той же странице.
import { useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { LoginScreen } from './LoginScreen';
import { useAuth } from './store';

/** `load` — один и тот же промис на процесс: центр поднимается один раз. */
function Center({ load }: { load: () => Promise<ReactNode> }) {
  const [center, setCenter] = useState<ReactNode>(null);
  useEffect(() => {
    let live = true;
    void load().then((node) => {
      if (live) setCenter(node);
    });
    return () => {
      live = false;
    };
  }, [load]);
  return center;
}

export function AuthGate({ load }: { load: () => Promise<ReactNode> }) {
  const auth = useAuth();
  const queryClient = useQueryClient();

  // Ушли на вход — кэш прошлой сессии не нужен: после входа страница перечитает всё заново.
  useEffect(() => {
    if (auth.view === 'login') queryClient.clear();
  }, [auth.view, queryClient]);

  if (auth.view === 'login') return <LoginScreen reason={auth.reason} />;
  if (auth.view !== 'app') return null;
  return <Center load={load} />;
}
