// Строки фабрики словами (CC-0180): предупреждения приходят английскими строками с приставкой
// `STUDIO …`, `HORIZON …`, `STALE …`. На виду — русский текст по приставке, сама строка — под
// «подробнее». Строка с другой приставкой (окно, пауза) показывается как есть: придумывать за
// фабрику нельзя. Центр в Studio ничего не пишет и не проверяет — тексты это и говорят.
export type LineKind = 'studio' | 'horizon' | 'stale' | 'other';

export function lineKind(line: string): LineKind {
  const m = /^(STUDIO|HORIZON|STALE)\b/.exec(line.trim());
  return m ? (m[1]!.toLowerCase() as LineKind) : 'other';
}

const ddmm = (day: string) => `${day.slice(8, 10)}.${day.slice(5, 7)}`;

function studioWords(line: string): string {
  if (line.includes('taken off its schedule'))
    return 'В Studio поставьте «Ограниченный доступ» и уберите дату публикации — вручную. Центр Studio не меняет и не проверяет: он правит только журнал и копилку.';
  if (line.includes('comes back from the')) {
    const on = / on (.+?) \(it stands at/.exec(line)?.[1];
    const when = !on || on === 'its slot' ? 'его новый слот' : on;
    return `Ролик возвращается из запаса, новой загрузки нет. В Studio поставьте «Отложенная публикация» на ${when} — вручную; сейчас там «Ограниченный доступ».`;
  }
  const read = /must read (.+?) in Studio/.exec(line)?.[1];
  return read
    ? `Ролик уже в Studio: дату там ставите вы, фабрика правит только журнал. В Studio должно стоять: ${read}.`
    : 'Ролик уже в Studio: дату там ставите вы, центр её не меняет.';
}

function horizonWords(line: string): string {
  const m = /^HORIZON \S+: (.+?) is past .*?\((\d+) дн\., до (\d{4}-\d{2}-\d{2})/.exec(line.trim());
  return m
    ? `${m[1]} — дальше горизонта ленты (${m[2]} дн., до ${ddmm(m[3]!)}). День ваш: запишется, как вы назвали.`
    : 'День дальше горизонта ленты. День ваш: запишется, как вы назвали.';
}

function staleWords(line: string): string {
  const days = /\((\d+) дн\./.exec(line)?.[1];
  return `Новость устарела${days ? ` (${days} дн.)` : ''}: поставится только по вашему решению.`;
}

/** Строка фабрики для человека: вид и текст; неизвестная приставка — как есть. */
export function lineWords(line: string): { kind: LineKind; text: string } {
  const kind = lineKind(line);
  if (kind === 'studio') return { kind, text: studioWords(line) };
  if (kind === 'horizon') return { kind, text: horizonWords(line) };
  if (kind === 'stale') return { kind, text: staleWords(line) };
  return { kind, text: line };
}

type Refusal = { slug?: string | null; message: string };

/**
 * Отказы плана, которых нет у правок (фабрика повторяет в `refusals` плана все отказы правок с их
 * слагом, а `why` — первый из них): их показываем над списком, остальные — только у своей правки.
 */
export function ownRefusals<R extends Refusal>(plan: {
  refusals: R[];
  items: { slug: string }[];
}): R[] {
  return plan.refusals.filter((r) => !(r.slug && plan.items.some((i) => i.slug === r.slug)));
}

/** Отказ из `why` уже написан у своей правки — над списком его не повторять. */
export const whyIsOnItem = (plan: { why?: string | null; items: { refusals: Refusal[] }[] }) =>
  !!plan.why && plan.items.some((i) => i.refusals.some((r) => r.message === plan.why));

/** `why` плана, если его текст не стоит в списке отказов над правками и не у самой правки. */
export function headWhy<R extends Refusal>(plan: {
  why?: string | null;
  refusals: R[];
  items: { slug: string; refusals: Refusal[] }[];
}): string | null {
  if (!plan.why || whyIsOnItem(plan)) return null;
  return ownRefusals(plan).some((r) => r.message === plan.why) ? null : plan.why;
}
