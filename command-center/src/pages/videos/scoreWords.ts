// Слова оценки ролика (CC-0125): цвет тира, где находка, цена, статус цен, разбор находок.
import { fmtPoints, type TierLevel, type VideoScoreFinding } from '@/api/score';

import { timecode } from './format';

/** Цвет ступени тира — переменная темы; неизвестный тир — приглушённый. */
export function tierColor(level: TierLevel): string {
  return level == null ? 'var(--muted-foreground)' : `var(--tier-${level})`;
}

const MINUS = '−';
export const price = (n: number) =>
  n < 0 ? `${MINUS}${fmtPoints(-n)}` : n > 0 ? `+${fmtPoints(n)}` : '0';

/** Имя файла шота без пути (пути пула — только под «подробнее»). */
export const shotFile = (shot: string) => shot.split(/[\\/]/).at(-1) ?? shot;

/** Кадр словами: «a04_mine-cart.mp4» → «mine cart» (без номера, расширения и пути) — запасной
 * путь, когда фабрика не прислала `shot_ru` (договор до 0.58.0). */
export function shotName(shot: string): string {
  const base = shotFile(shot)
    .replace(/\.[a-z0-9]{2,4}$/i, '')
    .replace(/^[a-z]?\d+[_-]/i, '')
    .replace(/[_-]+/g, ' ')
    .trim();
  return base || shotFile(shot);
}

/** Стадии оценки словами — если API не дал своей подписи. */
export const STAGE_TEXT: Record<string, string> = {
  '6b': 'проверка сценария',
  plan: 'план монтажа',
  render: 'рендер',
  qc: 'проверка качества',
  judge: 'судья кадров',
};

/** Где находка, словами: блоки, время, шот, хук. */
export function whereText(f: VideoScoreFinding): string | null {
  const parts: string[] = [];
  const w = (f.where ?? {}) as { blocks?: unknown; block?: unknown; shot?: unknown };
  const blocks = Array.isArray(w.blocks) ? w.blocks : null;
  if (blocks?.length)
    parts.push(blocks.length === 1 ? `блок ${blocks[0]}` : `блоки ${blocks.join(', ')}`);
  else if (f.block != null && f.block !== '') parts.push(`блок ${f.block}`);
  if (typeof f.t === 'number') parts.push(`на ${timecode(f.t)}`);
  const shot = f.shot ?? (typeof w.shot === 'string' ? w.shot : null);
  const shown = f.shot_ru?.trim() || (shot ? shotName(shot) : null);
  if (shown) parts.push(`кадр «${shown}»`);
  if (f.hook) parts.push('в хуке — первые 5 секунд, цена выше');
  return parts.length ? parts.join(' · ') : null;
}

/** Заметка находки без абсолютных путей пула: путь → имя файла. */
export const cleanNote = (note: string) => note.replace(/(?:\/[^\s/()]+)+\/([^\s/()]+)/g, '$1');

/** Заметка находки по-русски (0.58.0, CF-0751); нет — null: сырая `note` только под «подробнее». */
export const noteRu = (f: VideoScoreFinding): string | null => f.note_ru?.trim() || null;

/** Правило словами; подписи у фабрики нет — «другое правило» (код — под «подробнее»). */
export const ruleName = (f: VideoScoreFinding) => f.label_ru || 'другое правило';

/** Полный шот находки (для «подробнее»). */
export const shotOf = (f: VideoScoreFinding): string | null => {
  const w = (f.where ?? {}) as { shot?: unknown };
  return f.shot ?? (typeof w.shot === 'string' ? w.shot : null);
};

export function pricesText(status: string | null | undefined): string | null {
  if (!status) return null;
  if (status === 'signed') return 'Цены правил подписаны пользователем.';
  if (status === 'draft')
    return 'Цены правил — черновик: их ещё не подписали, они могут поменяться.';
  return `Цены правил: ${status}.`;
}

/** Разложить находки: жёсткие, штрафы по цене (дорогие первыми), прогноз. */
export function groupFindings(findings: VideoScoreFinding[]) {
  const hard = findings.filter((f) => f.hard);
  const forecast = findings.filter((f) => !f.hard && f.forecast);
  const penalties = findings
    .filter((f) => !f.hard && !f.forecast)
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0));
  return { hard, penalties, forecast };
}

/** Куда ведёт «к моменту ▶» вне страницы ролика. */
export function momentHref(href: string, t: number): string {
  const [path, query = ''] = href.split('?');
  const p = new URLSearchParams(query);
  p.set('t', String(Math.round(t * 100) / 100));
  return `${path}?${p.toString()}`;
}
