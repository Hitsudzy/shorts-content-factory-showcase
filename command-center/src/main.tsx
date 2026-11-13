import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { createBrowserRouter, RouterProvider } from 'react-router';

import { bootAuth } from './api/auth';
import { createQueryClient } from './app/queryClient';
import { routerBasename, routes } from './app/routes';
import { applyTheme, readSavedTheme } from './app/theme';
import { AuthGate } from './auth/AuthGate';
import { bootTraining, trainingRequested } from './training/mode';
import './fonts';
import './index.css';

const root = document.getElementById('root');
if (!root) throw new Error('#root не найден в index.html');

// Тема — до первого рендера, чтобы светлая не мелькала тёмной.
applyTheme(readSavedTheme());

// Центр — один раз на вкладку, и только после входа (CC-0037). Тренировка (CC-0073): если
// вкладка в ней — демо-сервер поднимается до первого рендера центра, то есть до первого запроса.
// Иначе — живой центр; кусок с демо-кодом не грузится.
let center: Promise<ReactNode> | null = null;
const loadCenter = (): Promise<ReactNode> =>
  (center ??= bootTraining().then(() => {
    const router = createBrowserRouter(routes, { basename: routerBasename });
    return <RouterProvider router={router} />;
  }));

// Сначала — нужен ли вход (CC-0037): до входа закрыто всё, кроме `/api/auth/*` и статики.
void bootAuth({ training: trainingRequested() }).then(() => {
  const queryClient = createQueryClient();
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <AuthGate load={loadCenter} />
      </QueryClientProvider>
    </StrictMode>,
  );
});
