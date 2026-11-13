// CC-0004: типы API из контракта фабрики и проверка, что они не отстали от него.
//
//   node scripts/api-contract.ts types   — `npm run api:types`: перегенерировать
//   node scripts/api-contract.ts check   — `npm run api:check` (входит в typecheck и build)
//
// Контракт — `api/openapi.json` корня фабрики. Где он лежит: env `CC_OPENAPI` (путь;
// относительный — от корня этого репо), по умолчанию `../api/openapi.json` (центр живёт
// в `<корень фабрики>/frontend/`). `CC_OPENAPI=off` — не искать контракт вовсе.
//
// В репо коммитятся три файла, все производные от контракта:
//   src/api/openapi.snapshot.json — побайтная копия контракта, из которой сделаны типы;
//   src/api/schema.gen.ts         — типы openapi-typescript (`paths`, `components`);
//   src/api/contract.gen.ts       — `CONTRACT`: sha256 и info.version снимка.
// sha256 считается по сырым байтам — так же, как `contract_sha` в shared/agents_lock.py.
//
// check падает, когда:
//   * сгенерированные файлы не совпадают с тем, что дал бы снимок (правка руками / не
//     перегенерировали после правки снимка) — проверяется всегда, фабрика не нужна;
//   * контракт найден, а его sha256 не равен sha256 снимка — контракт поменялся, типы нет;
//   * контракта нет, но его потребовали: путь задан явно в CC_OPENAPI или CC_OPENAPI_REQUIRED=1.
// Контракта нет по пути по умолчанию (CI, тесты, корень фабрики ещё без API) — это
// предупреждение, не ошибка: сборка воспроизводима из закоммиченного снимка.
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// openapi-typescript грузится лениво: vite.config.ts импортирует этот файл и в dev/тестах.
import type { OpenAPI3 } from 'openapi-typescript';

export const REPO_ROOT = fileURLToPath(new URL('..', import.meta.url));
export const CONTRACT_NAME = 'api/openapi.json';
const DEFAULT_SOURCE = '../api/openapi.json';
const SNAPSHOT = 'src/api/openapi.snapshot.json';
const SCHEMA_TS = 'src/api/schema.gen.ts';
const CONTRACT_TS = 'src/api/contract.gen.ts';

/** Как прошла сверка с живым контрактом фабрики. */
export type Live = 'match' | 'absent' | 'off';

export type CheckResult = {
  ok: boolean;
  /** sha256 снимка — контракта, под который собраны типы. */
  sha256: string;
  /** info.version снимка. */
  version: string;
  live: Live;
  errors: string[];
  warnings: string[];
};

type Env = Record<string, string | undefined>;

const sha256 = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const repoPath = (p: string) => resolve(REPO_ROOT, p);
const shown = (p: string) => {
  const r = relative(process.cwd(), p);
  return r && !r.startsWith('..') ? r : p;
};

/** Откуда брать контракт: null — `CC_OPENAPI=off`. */
export function contractSource(env: Env = process.env): { path: string; explicit: boolean } | null {
  const raw = env.CC_OPENAPI?.trim();
  if (raw === 'off') return null;
  const p = raw || DEFAULT_SOURCE;
  return { path: isAbsolute(p) ? p : repoPath(p), explicit: !!raw };
}

async function readOptional(path: string): Promise<Buffer | null> {
  try {
    return await readFile(path);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw e;
  }
}

type Spec = { info?: { version?: unknown; title?: unknown } };

/** Содержимое двух .gen.ts, которое даёт контракт `bytes`. */
export async function generate(
  bytes: Buffer,
): Promise<{ schema: string; contract: string; sha256: string; version: string }> {
  const spec = JSON.parse(bytes.toString('utf8')) as Spec;
  const sum = sha256(bytes);
  const version = typeof spec.info?.version === 'string' ? spec.info.version : 'unknown';
  const title = typeof spec.info?.title === 'string' ? spec.info.title : '';
  const head = `// Сгенерировано \`npm run api:types\` из ${CONTRACT_NAME} (sha256 ${sum}). Руками не править.\n`;
  const { default: openapiTS, astToString } = await import('openapi-typescript');
  const ast = await openapiTS(spec as OpenAPI3);
  const schema = head + astToString(ast);
  const contract =
    head +
    `\n/** Контракт API, под который собран центр (CC-0004). Его же пишет сборка в \`dist/contract.json\`. */\n` +
    `export const CONTRACT = {\n` +
    `  contract: ${JSON.stringify(CONTRACT_NAME)},\n` +
    `  sha256: ${JSON.stringify(sum)},\n` +
    `  version: ${JSON.stringify(version)},\n` +
    `  title: ${JSON.stringify(title)},\n` +
    `} as const;\n`;
  return { schema, contract, sha256: sum, version };
}

/** `api:types`: снимок + типы из текущего контракта. */
export async function writeTypes(env: Env = process.env): Promise<string> {
  const src = contractSource(env);
  if (!src)
    throw new Error('CC_OPENAPI=off: генерировать не из чего — укажите путь к openapi.json');
  const bytes = await readOptional(src.path);
  if (!bytes) throw new Error(`контракт не найден: ${src.path} (задайте CC_OPENAPI)`);
  const out = await generate(bytes);
  await writeFile(repoPath(SNAPSHOT), bytes);
  await writeFile(repoPath(SCHEMA_TS), out.schema);
  await writeFile(repoPath(CONTRACT_TS), out.contract);
  return `типы API из ${shown(src.path)}: info.version ${out.version}, sha256 ${out.sha256.slice(0, 12)}`;
}

/** `api:check`: типы соответствуют снимку, снимок — контракту фабрики. */
export async function checkContract(env: Env = process.env): Promise<CheckResult> {
  const errors: string[] = [];
  const warnings: string[] = [];
  const fix = 'запустите `npm run api:types` (CC_OPENAPI — путь к openapi.json фабрики)';

  const snap = await readOptional(repoPath(SNAPSHOT));
  if (!snap) {
    return {
      ok: false,
      sha256: '',
      version: '',
      live: 'off',
      warnings,
      errors: [`нет ${SNAPSHOT} — ${fix}`],
    };
  }
  const want = await generate(snap);
  for (const [file, text] of [
    [SCHEMA_TS, want.schema],
    [CONTRACT_TS, want.contract],
  ] as const) {
    const have = await readOptional(repoPath(file));
    if (have?.toString('utf8') !== text) {
      errors.push(
        `${file} не соответствует ${SNAPSHOT} (правили руками или не перегенерировали) — ${fix}`,
      );
    }
  }

  let live: Live = 'off';
  const src = contractSource(env);
  if (src) {
    const bytes = await readOptional(src.path);
    if (bytes) {
      live = 'match';
      const sum = sha256(bytes);
      if (sum !== want.sha256) {
        errors.push(
          `контракт ${shown(src.path)} поменялся (sha256 ${sum.slice(0, 12)}), ` +
            `а типы собраны под ${want.sha256.slice(0, 12)} (info.version ${want.version}) — ${fix}`,
        );
      }
    } else if (src.explicit || env.CC_OPENAPI_REQUIRED === '1') {
      live = 'absent';
      errors.push(`контракт не найден: ${src.path}`);
    } else {
      live = 'absent';
      warnings.push(
        `контракт не найден (${shown(src.path)}) — сверяю только со снимком ${SNAPSHOT}; ` +
          `CC_OPENAPI задаёт путь, CC_OPENAPI_REQUIRED=1 делает отсутствие ошибкой`,
      );
    }
  }
  return {
    ok: errors.length === 0,
    sha256: want.sha256,
    version: want.version,
    live,
    errors,
    warnings,
  };
}

/** Штамп сборки `dist/contract.json` (CC-0004): под какой контракт собран центр. */
export function contractStamp(r: CheckResult): string {
  const stamp = {
    contract: CONTRACT_NAME,
    sha256: r.sha256,
    version: r.version,
    // match — сверен с контрактом фабрики при сборке; absent — его не было, только снимок;
    // off — сверку выключили (CC_OPENAPI=off).
    live: r.live,
    built_by: 'vite build (CC-0004)',
  };
  return JSON.stringify(stamp, null, 2) + '\n';
}

async function main(cmd: string | undefined): Promise<number> {
  if (cmd === 'types') {
    console.log(await writeTypes());
    return 0;
  }
  if (cmd === 'check') {
    const r = await checkContract();
    for (const w of r.warnings) console.warn(`api:check: предупреждение: ${w}`);
    for (const e of r.errors) console.error(`api:check: ${e}`);
    if (r.ok)
      console.log(
        `api:check: типы под контракт ${r.version} (sha256 ${r.sha256.slice(0, 12)}), сверка: ${r.live}`,
      );
    return r.ok ? 0 : 1;
  }
  console.error('usage: node scripts/api-contract.ts types|check');
  return 2;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv[2]).then(
    (code) => process.exit(code),
    (e: unknown) => {
      console.error(`api-contract: ${e instanceof Error ? e.message : String(e)}`);
      process.exit(1);
    },
  );
}
