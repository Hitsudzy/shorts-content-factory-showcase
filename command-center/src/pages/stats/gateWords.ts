// Слова цены воротец (CC-0115 → CC-0100): правило фабрики — по-русски (имя правила — только
// под «подробнее»), вердикт, цена, подпись и решение пользователя.
import type { Tone } from '@/components/common/Status';
import type { GatePriceResult } from '@/api/gatePrices';
import { plural } from '@/pages/batches/format';

/** Правила воротец фабрики (`gate_price.RULES`) — что они отказывают, словами. */
const RULE: Record<string, string> = {
  'content_researcher.tail_after_last_anchor': 'Речь после последнего кадра-якоря',
  'footage_indexer.no_second_source': 'Тема без второго источника футажа',
  'frame_judge.foreign_core': 'Чужой кадр в главном месте ролика',
  'orchestrator.stopcock': 'Стоп-кран: сценариев нет — батч закрывается',
  'video_editor.meme_captions': 'Мем без наших субтитров',
  'video_editor.panel_in_frame': 'Обрезок экранной плашки у края кадра',
  'video_editor.pool_holds_video': 'Застывшие кадры из-за тонкого пула',
  'video_editor.safe_area': 'Важное за краем экрана телефона',
  'video_editor.two_source_gate': 'Ролик из одного источника',
  'video_editor.subtitle_overlap': 'Субтитры поверх текста в кадре',
};

/** Правило словами; неизвестное — общими словами (само имя — под «подробнее»). */
export const ruleText = (rule: string) => RULE[rule] ?? 'Правило воротец без имени в центре';

export const VERDICT: Record<
  GatePriceResult['verdict'],
  { label: string; tone: Tone; tip: string }
> = {
  enforce: {
    label: 'отказ',
    tone: 'danger',
    tip: 'Правило отказывает: ролик или тема дальше не идут.',
  },
  warn: {
    label: 'предупреждение',
    tone: 'warn',
    tip: 'Правило только предупреждает — ролик идёт дальше, пока цену не подписали.',
  },
  penalty: {
    label: 'штраф к оценке',
    tone: 'idle',
    tip: 'Правило не отказывает, а снимает очки с оценки ролика.',
  },
};

export const MODE: Record<string, string> = {
  measure: 'только замер',
  warn: 'предупреждение',
};

/** «из 1 готового ролика», «из 15 готовых роликов». */
const ofVideos = (n: number) =>
  `из ${n} ${plural(n, 'готового ролика', 'готовых роликов', 'готовых роликов')}`;
const batches = (n: number) => `${n} ${plural(n, 'батча', 'батчей', 'батчей')}`;

/** «убил бы 3 из 15 готовых роликов» / «не измерена». */
export function priceText(r: Pick<GatePriceResult, 'price' | 'ready'>): string {
  if (r.price == null) return 'не измерена';
  if (r.price === 0) return `не убил бы ни одного ${ofVideos(r.ready)}`;
  return `убил бы ${r.price} ${ofVideos(r.ready)}`;
}

/** «по 4 из 5 батчей окна». */
export const basisText = (r: Pick<GatePriceResult, 'measured_on' | 'of'>) =>
  r.measured_on
    ? `по ${r.measured_on} из ${batches(r.of)} окна`
    : `ни один из ${batches(r.of)} окна не мог её показать`;

const day = (v: unknown) => {
  if (typeof v !== 'string') return null;
  const m = v.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}` : v;
};

/** Что значит подписанная цена — подсказка у подписи. */
export const SIGNED_TIP =
  'Цена — сколько готовых роликов окна правило убило бы отказом. Подписывая её, вы согласились терять столько роликов ради этого правила.';

/** «Подписано 05.10: можно терять 1 готовый ролик». */
export function signatureText(sig: Record<string, unknown> | null | undefined): string | null {
  if (!sig) return null;
  const when = day(sig.date);
  const n = typeof sig.price === 'number' ? sig.price : null;
  const price =
    n == null
      ? ''
      : `: можно терять ${n} ${plural(n, 'готовый ролик', 'готовых ролика', 'готовых роликов')}`;
  return `Подписано${when ? ` ${when}` : ''}${price}`;
}

/** Что делает код правила сейчас, пока ничто другое не сказано (`mode`). */
export const NOW_MODE: Record<string, string> = {
  measure: 'сейчас фабрика: только замеряет',
  warn: 'сейчас фабрика: только предупреждает',
};

/** «Ваше решение 28.09: предупреждение». */
export function decisionText(dec: Record<string, unknown> | null | undefined): string | null {
  if (!dec) return null;
  const when = day(dec.date);
  const mode = typeof dec.mode === 'string' ? (MODE[dec.mode] ?? dec.mode) : 'без режима';
  return `Решение${when ? ` ${when}` : ''}: ${mode}`;
}
