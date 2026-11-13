import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';

import {
  resetAnalytics,
  resetAuthMock,
  resetBatches,
  resetChannels,
  resetDev,
  resetGates,
  resetMaintenance,
  resetMemes,
  resetNotify,
  resetOAuth,
  resetPublish,
  resetQuestions,
  resetRequests,
  resetRights,
  resetSchedule,
  resetStudio,
  resetVersions,
  resetVideos,
} from '@/mocks/handlers';
import { resetWritesInFlight } from '@/api/writeLock';
import { resetAuth } from '@/auth/store';
import { server } from '@/mocks/server';
import { ASYNC_UTIL_TIMEOUT_MS } from '@/test/timeouts';

// CC-0042: под нагрузкой ленивые чанки и ответы MSW приходят за секунды, а штатная секунда
// `findBy*`/`waitFor` их не дожидается. Явные `{ timeout }` в тестах не нужны — общий потолок.
configure({ asyncUtilTimeout: ASYNC_UTIL_TIMEOUT_MS });

// Запрос мимо подставного API = ошибка, а не поход в сеть.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetChannels();
  resetSchedule();
  resetBatches();
  resetVideos();
  resetPublish();
  resetQuestions();
  resetRequests();
  resetAnalytics();
  resetMemes();
  resetNotify();
  resetOAuth();
  resetWritesInFlight();
  resetRights();
  resetStudio();
  resetGates();
  resetVersions();
  resetMaintenance();
  resetAuthMock();
  resetAuth();
  resetDev();
});
afterAll(() => server.close());
