// CC-0152 (фабрика 2.20, договор 0.69.0): подставные размыкатель в проверке запуска, строка
// `repeat_held` в истории, принятый ролик «не в копилке».
import { LAUNCH_BUDGET } from './batchActions';
import { createBatchesBackend, REPEAT_HELD, routeBatches } from './batches';
import { MOCK_BREAKER } from './schedule';
import {
  createVideosBackend,
  LEFT_OUT_ALERT,
  LEFT_OUT_NAMESAKE,
  LEFT_OUT_SLUG,
  OLDER,
} from './videos';

type Plan = {
  skipped: string[];
  breaker?: { held?: boolean } | null;
  budget?: { reason?: string } | null;
};
const plan = (b: ReturnType<typeof createBatchesBackend>, channel: string) =>
  routeBatches(b, 'POST', new URL('http://x/api/batches/launch/plan'), { channel })!.body as Plan;

describe('CC-0152: подставные данные', () => {
  it('проверка запуска: размыкатель и бюджет — только когда заданы; null убирает', () => {
    const b = createBatchesBackend();
    expect(plan(b, 'example-film').breaker ?? null).toBeNull();
    b.actions.setBreaker();
    const p = plan(b, 'example-film');
    expect(p.breaker?.held).toBe(true);
    expect(p.skipped).toContain(MOCK_BREAKER.line);
    b.actions.setBudget();
    expect(plan(b, 'example-tech').budget?.reason).toBe(LAUNCH_BUDGET.reason);
    b.actions.setBreaker(null, 'example-film');
    expect(plan(b, 'example-film').breaker ?? null).toBeNull();
  });

  it('история запусков: `repeat_held` — запуск без батча, только у своего канала', () => {
    const b = createBatchesBackend();
    const all = b.history(50).body as { launches: { kind?: string }[] };
    expect(all.launches.filter((l) => l.kind === 'repeat_held')).toEqual([REPEAT_HELD]);
    const reel = b.history(50, 'example-film').body as { launches: { kind?: string }[] };
    expect(reel.launches.some((l) => l.kind === 'repeat_held')).toBe(false);
  });

  it('приёмка: «да» ролику usb-c-myths старого батча — не в копилке, с тёзкой', () => {
    const v = createVideosBackend();
    const r = v.accept(OLDER, LEFT_OUT_SLUG, {
      verdict: 'yes',
      words: `${LEFT_OUT_SLUG} — да`,
    });
    expect(r.status).toBe(200);
    const body = r.body as {
      queued?: { left_out?: boolean; text_ru?: string };
      left_out?: { alert_ru?: string; namesake?: unknown } | null;
    };
    expect(body.queued?.left_out).toBe(true);
    expect(body.queued?.text_ru).toMatch(/^НЕ В КОПИЛКЕ: /);
    expect(body.left_out?.alert_ru).toBe(LEFT_OUT_ALERT);
    expect(body.left_out?.namesake).toEqual(LEFT_OUT_NAMESAKE);
  });
});
