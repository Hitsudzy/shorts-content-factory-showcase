import type { RouteObject } from 'react-router';

import { NotFound } from '@/pages/NotFound';
import { Overview } from '@/pages/overview/Overview';
import { Placeholder } from '@/pages/Placeholder';

import { AREAS } from './areas';
import { Layout } from './Layout';
import { SkeletonPage } from '@/components/common/Skeletons';

// Каналы грузятся отдельным куском (там же редактор JSON): главной он не нужен.
const channels: RouteObject = {
  path: 'channels',
  children: [
    {
      index: true,
      lazy: async () => ({
        Component: (await import('@/pages/channels/ChannelsList')).ChannelsList,
      }),
    },
    {
      // «Новый канал» (CC-0009): статичный путь главнее `:channel`.
      path: 'new',
      lazy: async () => ({ Component: (await import('@/pages/channels/NewChannel')).NewChannel }),
    },
    {
      path: ':channel',
      lazy: async () => ({ Component: (await import('@/pages/channels/ChannelPage')).ChannelPage }),
    },
  ],
};

// «Батчи» (CC-0050…0052) — тоже своим куском.
const batches: RouteObject = {
  path: 'batches',
  lazy: async () => ({ Component: (await import('@/pages/batches/Batches')).Batches }),
};

// «Ролики» (CC-0061…0063) — своим куском.
const videos: RouteObject = {
  path: 'videos',
  lazy: async () => ({ Component: (await import('@/pages/videos/Videos')).Videos }),
};

// «Публикация» (CC-0067…0069) — своим куском.
const publishing: RouteObject = {
  path: 'publishing',
  lazy: async () => ({ Component: (await import('@/pages/publishing/Publishing')).Publishing }),
};

// «Вопросы» (CC-0017) — своим куском.
const questions: RouteObject = {
  path: 'questions',
  lazy: async () => ({ Component: (await import('@/pages/questions/Questions')).Questions }),
};

// «Статистика и аналитик» (CC-0021) — своим куском.
const stats: RouteObject = {
  path: 'stats',
  lazy: async () => ({ Component: (await import('@/pages/stats/Stats')).Stats }),
};

// «Мемы» (CC-0025) — своим куском.
const memes: RouteObject = {
  path: 'memes',
  lazy: async () => ({ Component: (await import('@/pages/memes/Memes')).Memes }),
};

// «Уведомления и напоминания» (CC-0027) — своим куском.
const notifications: RouteObject = {
  path: 'notifications',
  lazy: async () => ({ Component: (await import('@/pages/notify/Notify')).Notify }),
};

// «Токены, OAuth и данные API» (CC-0029) — своим куском.
const tokens: RouteObject = {
  path: 'tokens',
  lazy: async () => ({ Component: (await import('@/pages/oauth/OAuth')).OAuth }),
};

// «Версии и агенты» (CC-0031) — своим куском.
const versions: RouteObject = {
  path: 'versions',
  lazy: async () => ({ Component: (await import('@/pages/versions/Versions')).Versions }),
};

// «Обслуживание и расход» (CC-0033) — своим куском.
const maintenance: RouteObject = {
  path: 'maintenance',
  lazy: async () => ({
    Component: (await import('@/pages/maintenance/Maintenance')).Maintenance,
  }),
};

// «Разработка» (CC-0124) — своим куском: список и дорожная карта, карточка задачи `/dev/<id>`.
const dev: RouteObject = {
  path: 'dev',
  children: [
    { index: true, lazy: async () => ({ Component: (await import('@/pages/dev/Dev')).Dev }) },
    {
      path: ':id',
      lazy: async () => ({ Component: (await import('@/pages/dev/TaskCard')).TaskCard }),
    },
  ],
};

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    // Первая загрузка сразу на ленивую страницу (например, /channels/…): пока грузится кусок.
    hydrateFallbackElement: <SkeletonPage />,
    children: [
      ...AREAS.map((area): RouteObject => {
        if (area.path === '') return { index: true, element: <Overview /> };
        if (area.path === 'channels') return channels;
        if (area.path === 'batches') return batches;
        if (area.path === 'videos') return videos;
        if (area.path === 'publishing') return publishing;
        if (area.path === 'questions') return questions;
        if (area.path === 'stats') return stats;
        if (area.path === 'memes') return memes;
        if (area.path === 'notifications') return notifications;
        if (area.path === 'tokens') return tokens;
        if (area.path === 'versions') return versions;
        if (area.path === 'maintenance') return maintenance;
        if (area.path === 'dev') return dev;
        return { path: area.path, element: <Placeholder area={area} /> };
      }),
      { path: '*', element: <NotFound /> },
    ],
  },
];

/** basename роутера = базовый путь сборки (CC_BASE_PATH) без хвостового слэша. */
export const routerBasename = import.meta.env.BASE_URL.replace(/\/$/, '') || '/';
