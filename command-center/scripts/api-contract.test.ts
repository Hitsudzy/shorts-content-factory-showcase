// @vitest-environment node
import { copyFile, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { checkContract, contractSource, contractStamp, REPO_ROOT } from './api-contract.ts';

// Контракт фабрики здесь не нужен: подставной — копия закоммиченного снимка во временной папке.
const SNAPSHOT = join(REPO_ROOT, 'src/api/openapi.snapshot.json');
let dir = '';

beforeAll(async () => {
  dir = await mkdtemp(join(tmpdir(), 'cc-contract-'));
  await copyFile(SNAPSHOT, join(dir, 'same.json'));
  const changed = JSON.parse(await readFile(SNAPSHOT, 'utf8'));
  changed.info.version = '9.9.9';
  await writeFile(join(dir, 'changed.json'), JSON.stringify(changed, null, 2));
});
afterAll(() => rm(dir, { recursive: true, force: true }));

describe('сверка типов API с контрактом', { timeout: 30_000 }, () => {
  it('тот же контракт — ок, штамп несёт sha256 снимка', async () => {
    const r = await checkContract({ CC_OPENAPI: join(dir, 'same.json') });
    expect(r.errors).toEqual([]);
    expect(r.live).toBe('match');
    const stamp = JSON.parse(contractStamp(r));
    expect(stamp).toMatchObject({ contract: 'api/openapi.json', sha256: r.sha256, live: 'match' });
    expect(stamp.sha256).toMatch(/^[0-9a-f]{64}$/);
  });

  it('контракт поменялся, а типы нет — ошибка с подсказкой api:types', async () => {
    const r = await checkContract({ CC_OPENAPI: join(dir, 'changed.json') });
    expect(r.ok).toBe(false);
    expect(r.errors.join('\n')).toMatch(/поменялся.*npm run api:types/);
  });

  it('явно заданный, но отсутствующий контракт — ошибка', async () => {
    const r = await checkContract({ CC_OPENAPI: join(dir, 'missing.json') });
    expect(r.ok).toBe(false);
    expect(r.live).toBe('absent');
  });

  it('CC_OPENAPI=off — сверка только со снимком', async () => {
    const r = await checkContract({ CC_OPENAPI: 'off' });
    expect(r).toMatchObject({ ok: true, live: 'off', warnings: [] });
  });

  it('путь по умолчанию — ../api/openapi.json от корня репо', () => {
    expect(contractSource({})).toEqual({
      path: join(REPO_ROOT, '../api/openapi.json'),
      explicit: false,
    });
    expect(contractSource({ CC_OPENAPI: 'off' })).toBeNull();
  });
});
