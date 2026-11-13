// Банки мемов по каналам (CC-0025): каналы одного банка — одна строка выбора.
import type { MemeBankRow } from '@/api/memes';

export type Group = { bank: string | null; rows: MemeBankRow[] };

/** Каналы одного банка — одна строка выбора: черновик и разбор у них общие. */
export function groupsOf(rows: MemeBankRow[]): Group[] {
  const out: Group[] = [];
  for (const r of rows) {
    const g = r.bank ? out.find((x) => x.bank === r.bank) : undefined;
    if (g) g.rows.push(r);
    else out.push({ bank: r.bank ?? null, rows: [r] });
  }
  return out;
}

/** По умолчанию — банк, где больше всего ждут решения. */
export function defaultChannel(groups: Group[]): string | null {
  const open = groups.filter((g) => g.bank && !g.rows[0]!.error);
  const best = [...open].sort((a, b) => b.rows[0]!.pending - a.rows[0]!.pending)[0];
  return best?.rows[0]!.channel ?? null;
}
