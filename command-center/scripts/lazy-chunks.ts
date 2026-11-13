// CC-0073: демо-код тренировки (MSW, подставной API `src/mocks/*`, демо-сервер и панель) — только
// в ленивых кусках. Сборка проверяет граф кусков: то, что браузер грузит при обычном открытии
// центра (входной кусок и всё, что он импортирует статически), не содержит ни одного такого
// модуля; демо-сервер при этом есть — отдельным куском за динамическим `import()`.
// Проверка — в плагине сборки (vite.config.ts): нарушение роняет `vite build`.

/** То, что нужно проверке от куска сборки (Rollup/Rolldown `OutputChunk`). */
export type ChunkInfo = {
  type: 'chunk';
  fileName: string;
  isEntry: boolean;
  imports: string[];
  dynamicImports: string[];
  moduleIds: string[];
};
export type AssetInfo = { type: 'asset'; fileName: string };
export type BundleInfo = Record<string, ChunkInfo | AssetInfo>;

/** Модули, которым не место в обычной загрузке центра. */
export const DEMO_ONLY: readonly RegExp[] = [
  /[\\/]node_modules[\\/]msw[\\/]/,
  /[\\/]node_modules[\\/]@mswjs[\\/]/,
  /[\\/]src[\\/]mocks[\\/]/,
  /[\\/]src[\\/]training[\\/](demo|checklist|TrainingLayer)\.tsx?$/,
];

/** Демо-сервер тренировки — его кусок должен быть в сборке, ленивым. */
export const DEMO_ENTRY = /[\\/]src[\\/]training[\\/]demo\.ts$/;

const chunks = (b: BundleInfo) =>
  Object.values(b).filter((c): c is ChunkInfo => c.type === 'chunk');

/** Входные куски и всё, что они тянут статически: это грузит обычное открытие центра. */
export function eagerChunks(bundle: BundleInfo): ChunkInfo[] {
  const byName = new Map(chunks(bundle).map((c) => [c.fileName, c]));
  const seen = new Set<string>();
  const queue = chunks(bundle).filter((c) => c.isEntry);
  const out: ChunkInfo[] = [];
  while (queue.length) {
    const c = queue.shift()!;
    if (seen.has(c.fileName)) continue;
    seen.add(c.fileName);
    out.push(c);
    for (const f of c.imports) {
      const next = byName.get(f);
      if (next) queue.push(next);
    }
  }
  return out;
}

/** Нарушения: демо-модули в обычной загрузке, или демо-сервера нет отдельным куском. */
export function lazyProblems(bundle: BundleInfo): string[] {
  const problems: string[] = [];
  const eager = eagerChunks(bundle);
  for (const c of eager) {
    for (const id of c.moduleIds) {
      if (DEMO_ONLY.some((re) => re.test(id)))
        problems.push(`${c.fileName}: демо-модуль в обычной загрузке — ${id}`);
    }
  }
  const eagerNames = new Set(eager.map((c) => c.fileName));
  const demo = chunks(bundle).find((c) => c.moduleIds.some((id) => DEMO_ENTRY.test(id)));
  if (!demo) problems.push('нет куска с демо-сервером тренировки (src/training/demo.ts)');
  else if (eagerNames.has(demo.fileName))
    problems.push(`${demo.fileName}: демо-сервер грузится при обычном открытии`);
  return problems;
}
