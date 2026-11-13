// Подставное «снять ролик окончательно» (CC-0107 фабрики, договор 0.58.0; экран — CC-0115 шаг 3),
// без сети. Как `api/withdrawal.py`: план ничего не пишет — тема ролика, `topic_status` сейчас и
// после, какие исходники пула снятие отпустит и какие ещё держат; без токена, если ролик уже
// снят или тема не находится. «Да» — `{confirm, answer}`: ответ проверяется до траты токена (без
// кириллицы — 422 `answer_required`, без имени ролика — 422 `answer_without_name`); `busy` —
// токен цел; иначе токен сгорает (чужой ролик — `confirm_mismatch`, устарел — `confirm_expired`),
// план пересчитывается (`check_changed` / `refused`), и строка `withdrawn` ложится в журнал.
// Ручки: `state.next` (`busy`, `check_changed`, `factory_broken` — одноразово), `state.noTopic`,
// `state.openBatches`, `expireTokens()`. Импорты — относительные (общий для Vitest и Playwright).
import type { components } from '../api/schema.gen';
import type { BatchReply } from './schedule';

type S = components['schemas'];
type Code = S['BatchProblem']['code'];

export type WithdrawOutcome = 'busy' | 'check_changed' | 'factory_broken';

const CYRILLIC = /[А-Яа-яЁё]/;
const JOURNAL = 'shared/footage/release-log.jsonl';
const LINE =
  'Сейчас с диска ничего не уходит: исходники уберёт pool-release --delete (месячный архив), когда тема закончена.';

const problem = (
  status: 404 | 409 | 422 | 500,
  code: Code,
  message: string,
  details: string[] = [],
): BatchReply<never> => ({ status, body: { message, code, details } });

export type WithdrawWorld = {
  /** Ролик есть в батче: его вердикт (`accepted`/`rejected`/null) — для `topic_status`. */
  videoOf: (batch: string, slug: string) => { verdict: string | null } | null;
  now: () => string;
};

export function createWithdraw(world: WithdrawWorld) {
  const tokens = new Map<string, { entry: string; fp: string; expires: number }>();
  let n = 0;
  const state = {
    life: 120,
    next: null as WithdrawOutcome | null,
    /** Записи о снятии (`withdrawn` в журнале пула). */
    journal: [] as Record<string, unknown>[],
    /** Ролики, чья тема не находится (без токена). */
    noTopic: new Set<string>(),
    /** Идущие батчи (`open_batches`): держат исходник темы. */
    openBatches: [] as string[],
    /** Ответы пользователя, принятые «да» (как есть). */
    answers: [] as string[],
    calls: [] as { kind: 'plan' | 'confirm'; entry: string; body: unknown }[],
  };

  const topicOf = (entry: string) =>
    state.noTopic.has(entry) ? null : `topic-${entry.split('/').at(-1)}`;

  function check(entry: string, verdict: string | null) {
    const topic = topicOf(entry);
    const before = state.journal.filter((r) => r.entry_id === entry);
    const now = verdict === 'accepted' ? 'accepted_not_published' : 'rejected_not_withdrawn';
    const status = topic ? { status: before.length ? 'withdrawn' : now, evidence: 'mock' } : null;
    const after = topic ? { status: 'withdrawn', evidence: 'mock' } : null;
    const slug = entry.split('/').at(-1)!;
    const frees = state.openBatches.length
      ? []
      : [{ video_id: `src-${slug}-1`, files: [`shared/footage/${slug}-1.mp4`], bytes: 48_234_496 }];
    const kept = state.openBatches.length
      ? [
          {
            video_id: `src-${slug}-1`,
            blocked_by: ['open_batch'],
            open_batches: [...state.openBatches],
            topics: { [topic ?? '-']: 'withdrawn' },
          },
        ]
      : [];
    let why: string | null = null;
    if (before.length)
      why = `${entry} уже снят окончательно (${String(before.at(-1)!.at)}) - записывать нечего.`;
    else if (!topic)
      why = `Тема ролика ${entry} не находится (ни 05-video-editor.json батча, ни другие батчи её не называют) - снятие ни на что не повлияет; ролик не снят.`;
    return {
      ok: why == null,
      why,
      entry_id: entry,
      topic_id: topic,
      status,
      status_after: after,
      withdrawn_before: before,
      frees,
      frees_bytes: frees.reduce((a, f) => a + f.bytes, 0),
      kept,
      open_batches: [...state.openBatches],
      journal: JOURNAL,
      by: 'user' as const,
      via: 'center' as const,
      deletes_now: false,
      line: LINE,
    };
  }

  const entryOf = (batch: string, slug: string) => `${batch}/${slug}`;

  function plan(batch: string, slug: string): BatchReply<S['WithdrawPlan']> {
    const v = world.videoOf(batch, slug);
    const entry = entryOf(batch, slug);
    state.calls.push({ kind: 'plan', entry, body: null });
    if (!v) return problem(404, 'unknown_video', `Ролика «${slug}» в батче «${batch}» нет.`);
    const out = check(entry, v.verdict);
    const fp = JSON.stringify(out);
    let confirm: string | null = null;
    if (out.ok) {
      confirm = `withdraw-${++n}`;
      tokens.set(confirm, { entry, fp, expires: Date.now() + state.life * 1000 });
    }
    return {
      status: 200,
      body: {
        ...out,
        action: 'video_withdraw',
        fingerprint: `sha256:${fp.length}-${n}`,
        confirm,
        expires_in_s: confirm ? state.life : null,
      },
    };
  }

  function confirm(batch: string, slug: string, raw: unknown): BatchReply<S['WithdrawResult']> {
    const entry = entryOf(batch, slug);
    state.calls.push({ kind: 'confirm', entry, body: raw });
    const v = world.videoOf(batch, slug);
    if (!v) return problem(404, 'unknown_video', `Ролика «${slug}» в батче «${batch}» нет.`);
    const b = (raw ?? {}) as { confirm?: string; answer?: unknown };
    const words = typeof b.answer === 'string' ? b.answer.trim() : '';
    if (!words || !CYRILLIC.test(words))
      return problem(
        422,
        'answer_required',
        'Снять ролик окончательно можно только вашим словом: напишите по-русски, что снимаете, и назовите ролик.',
        ['answer: empty or without a Cyrillic letter; the token is not spent'],
      );
    if (!words.toLowerCase().includes(slug.toLowerCase()))
      return problem(
        422,
        'answer_without_name',
        `Ответ не называет ролик «${slug}» - снятие записывается только под названным роликом.`,
        [`check_answer: the answer does not name '${slug}'`, 'the token is not spent'],
      );
    const next = state.next;
    state.next = null;
    if (next === 'busy')
      return problem(
        409,
        'busy',
        'Идёт другое снятие ролика - подождите и запросите план заново.',
        ['the withdrawal lock was not free in 30.0 s; the token is not spent'],
      );
    const got = tokens.get(b.confirm ?? '');
    if (!got)
      return problem(
        409,
        'confirm_unknown',
        'Подтверждение не найдено или уже использовано - запросите план заново.',
      );
    tokens.delete(b.confirm!);
    if (got.entry !== entry)
      return problem(
        409,
        'confirm_mismatch',
        `Подтверждение выдано для ${got.entry}, а не для ${entry} - ничего не записано.`,
      );
    if (got.expires <= Date.now())
      return problem(
        409,
        'confirm_expired',
        'Подтверждение устарело (живёт 120 с) - запросите план заново.',
      );
    if (next === 'factory_broken')
      return problem(
        500,
        'factory_broken',
        `Фабрика ответила ошибкой - ролик не снят; посмотрите ${JOURNAL}.`,
        ['OSError: disk full'],
      );
    const out = check(entry, v.verdict);
    if (next === 'check_changed' || JSON.stringify(out) !== got.fp) {
      if (!out.ok) return problem(409, 'refused', out.why!, ['the check changed since the plan']);
      return problem(
        409,
        'check_changed',
        'Проверка изменилась с момента плана - ролик не снят; посмотрите план заново.',
      );
    }
    const row = {
      event: 'withdrawn',
      entry_id: entry,
      topic_id: out.topic_id,
      answer: words,
      at: world.now(),
      task: 'CF-0358',
      by: 'user',
      via: 'center',
    };
    state.journal.push(row);
    state.answers.push(words);
    return {
      status: 200,
      body: {
        action: 'video_withdraw',
        entry_id: entry,
        written: true,
        row,
        by: 'user',
        via: 'center',
        journal: JOURNAL,
        frees: out.frees,
        status_after: out.status_after,
      },
    };
  }

  /** Все выданные токены устарели (как будто прошло 120 с). */
  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
  };

  return { state, plan, confirm, expireTokens };
}

export type WithdrawBackend = ReturnType<typeof createWithdraw>;
