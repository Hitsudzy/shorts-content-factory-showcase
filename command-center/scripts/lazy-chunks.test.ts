// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { eagerChunks, lazyProblems, type BundleInfo, type ChunkInfo } from './lazy-chunks.ts';

const chunk = (fileName: string, over: Partial<ChunkInfo> = {}): ChunkInfo => ({
  type: 'chunk',
  fileName,
  isEntry: false,
  imports: [],
  dynamicImports: [],
  moduleIds: [],
  ...over,
});

const R = '/repo';

function bundle(...cs: ChunkInfo[]): BundleInfo {
  return Object.fromEntries(cs.map((c) => [c.fileName, c]));
}

describe('ленивый демо-код тренировки', () => {
  const good = bundle(
    chunk('index.js', {
      isEntry: true,
      imports: ['mode.js'],
      dynamicImports: ['demo.js'],
      moduleIds: [`${R}/src/main.tsx`],
    }),
    chunk('mode.js', { moduleIds: [`${R}/src/training/mode.ts`] }),
    chunk('demo.js', {
      imports: ['mode.js'],
      moduleIds: [
        `${R}/src/training/demo.ts`,
        `${R}/src/mocks/publish.ts`,
        `${R}/node_modules/msw/lib/browser/index.mjs`,
      ],
    }),
  );

  it('обычная загрузка — вход и его статические импорты, без ленивых', () => {
    expect(eagerChunks(good).map((c) => c.fileName)).toEqual(['index.js', 'mode.js']);
    expect(lazyProblems(good)).toEqual([]);
  });

  it('моки или MSW в обычной загрузке — нарушение с именем модуля', () => {
    const bad = bundle(
      chunk('index.js', {
        isEntry: true,
        imports: ['shared.js'],
        moduleIds: [`${R}/src/main.tsx`],
      }),
      chunk('shared.js', {
        moduleIds: [`${R}/src/mocks/fixtures.ts`, `${R}/node_modules/@mswjs/interceptors/x.js`],
      }),
      chunk('demo.js', { moduleIds: [`${R}/src/training/demo.ts`] }),
    );
    expect(lazyProblems(bad)).toEqual([
      `shared.js: демо-модуль в обычной загрузке — ${R}/src/mocks/fixtures.ts`,
      `shared.js: демо-модуль в обычной загрузке — ${R}/node_modules/@mswjs/interceptors/x.js`,
    ]);
  });

  it('демо-сервер во входном куске или его нет вовсе — нарушение', () => {
    const inMain = bundle(
      chunk('index.js', {
        isEntry: true,
        moduleIds: [`${R}/src/main.tsx`, `${R}/src/training/demo.ts`],
      }),
    );
    expect(lazyProblems(inMain)).toEqual([
      `index.js: демо-модуль в обычной загрузке — ${R}/src/training/demo.ts`,
      'index.js: демо-сервер грузится при обычном открытии',
    ]);
    const none = bundle(chunk('index.js', { isEntry: true, moduleIds: [`${R}/src/main.tsx`] }));
    expect(lazyProblems(none)).toEqual([
      'нет куска с демо-сервером тренировки (src/training/demo.ts)',
    ]);
  });
});
