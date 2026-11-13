// Чистая логика мастера «Новый канал» (CC-0009): шаги, проверка входов по шаблону фабрики,
// черновик позиции поверх файла, который сделает фабрика, разница с шаблоном.
//
// Создание (`POST /api/channels`) принимает три входа — id, название, язык — и (договор 0.5.0)
// текст позиции целиком (`stance_text`): мастер вписывает фразу в файл позиции из dry-run, и
// фабрика пишет всё одним коммитом. Ключей, которых нет в шаблоне фабрики, мастер не
// придумывает: для них шаг — пояснение, что и где настраивается после создания.
import type { CheckLine, CreateResult, TemplateInput } from '@/api/channels';

import { readDoc, setValue, valueAt } from './fields';

export type StepId = 'name' | 'topic' | 'voice' | 'feeds' | 'publish' | 'review' | 'create';

export const STEPS: { id: StepId; label: string; tip: string }[] = [
  {
    id: 'name',
    label: 'Имя и id',
    tip: 'Идентификатор, название и язык канала — всё, из чего фабрика делает новый канал',
  },
  {
    id: 'topic',
    label: 'Тематика и позиция',
    tip: 'Позиция канала в одну фразу и что ещё о тематике настраивается потом',
  },
  {
    id: 'voice',
    label: 'Голос и паттерны',
    tip: 'Голос озвучки и паттерны роликов: где они настраиваются, когда у канала будет конвейер',
  },
  {
    id: 'feeds',
    label: 'Ленты и источники',
    tip: 'Откуда канал берёт истории и факты: где это настраивается после создания',
  },
  {
    id: 'publish',
    label: 'Публикация и окно',
    tip: 'Расписание батчей и публикация нового канала: с чем он создаётся',
  },
  {
    id: 'review',
    label: 'Проверка',
    tip: 'Что фабрика скажет про канал и какие файлы она запишет — до того, как что-то создано',
  },
  {
    id: 'create',
    label: 'Создать',
    tip: 'Создать канал и узнать, что ещё нужно до первого батча',
  },
];

export type Inputs = { channel_id: string; display_name: string; language: string };
export type InputName = keyof Inputs;

/** Адрес самого мастера — `/channels/new`: канал с таким id в центре не открылся бы. */
export const WIZARD_SLUG = 'new';

export function initialInputs(inputs: readonly TemplateInput[]): Inputs {
  const v: Inputs = { channel_id: '', display_name: '', language: '' };
  for (const i of inputs) v[i.name] = i.default ?? '';
  return v;
}

/** Что ушлёт мастер: пробелы по краям срезаны, пустой язык — значение фабрики по умолчанию. */
export function cleanInputs(v: Inputs): Inputs {
  return {
    channel_id: v.channel_id.trim(),
    display_name: v.display_name.trim(),
    language: v.language.trim(),
  };
}

/**
 * Проверка входа здесь же, пока человек печатает: обязательность и регулярка фабрики
 * (`pattern` шаблона). Остальное (занято ли имя и т. п.) говорит dry-run фабрики.
 */
export function localError(input: TemplateInput, raw: string): string | null {
  const value = raw.trim();
  if (!value) return input.required ? 'Нужно заполнить' : null;
  if (input.pattern) {
    let re: RegExp | null;
    try {
      re = new RegExp(input.pattern);
    } catch {
      re = null; // регулярка фабрики не по зубам JS — пусть скажет dry-run
    }
    if (re && !re.test(value)) {
      return input.name === 'channel_id'
        ? 'Латиница в нижнем регистре, цифры и дефис внутри, от 2 до 40 знаков, первая — буква'
        : input.name === 'language'
          ? 'Код языка: две строчные буквы, можно с регионом — en, ru, pt-BR'
          : 'Не подходит под правило фабрики';
    }
  }
  return null;
}

/** Своя проверка id на случай, если фабрика сама `new` не отклонит (до договора 0.5.0). */
export const WIZARD_SLUG_ERROR = `«${WIZARD_SLUG}» — адрес этого мастера в центре: страница такого канала не открылась бы`;

/**
 * Ошибки входов по полям: фабрики (из dry-run) и, запасной, своя — id `new`. Фабрика с 0.5.0
 * отклоняет `new` сама, и тогда виден её текст; своя строка — только если она промолчала.
 */
export function inputErrorsByField(
  inputs: Inputs,
  server: Partial<Record<InputName, string[]>>,
): Partial<Record<InputName, string[]>> {
  if (inputs.channel_id !== WIZARD_SLUG || server.channel_id?.length) return server;
  return { ...server, channel_id: [WIZARD_SLUG_ERROR] };
}

/** Ошибки позиции из отказа создания (`field` `stance`, `stance.channel_id`, …). */
export function stanceErrors(lines: readonly CheckLine[]): CheckLine[] {
  return lines.filter((l) => l.field === 'stance' || !!l.field?.startsWith('stance.'));
}

/**
 * Ошибки dry-run по входам: поле → строки. Строка — русская фабрики (`text_ru`; у входа она та же,
 * что `text`), иначе `text`; без технической приставки `поле:` и путей — они под «подробнее».
 */
export function serverErrors(lines: readonly CheckLine[]): {
  byField: Partial<Record<InputName, string[]>>;
  rest: CheckLine[];
} {
  const byField: Partial<Record<InputName, string[]>> = {};
  const rest: CheckLine[] = [];
  for (const l of lines) {
    const f = l.field as InputName | null;
    if (f === 'channel_id' || f === 'display_name' || f === 'language') {
      // Путь в скобках («(channels/x.json)») — только под «подробнее»: там вся строка.
      const why = (l.text_ru ?? l.text)
        .replace(new RegExp(`^${f}:\\s*`), '')
        .replace(/\s*\([^)]*\/[^)]*\)/g, '');
      (byField[f] ??= []).push(why.charAt(0).toUpperCase() + why.slice(1));
    } else rest.push(l);
  }
  return { byField, rest };
}

/** Убрать номера задач из пояснения фабрики: они — только под «подробнее». */
export function stripTasks(note: string | null | undefined): string {
  const s = (note ?? '')
    .replace(/^(?:CF|CC)-\d{3,5}\b(?:\s*\([^)]*\))?\s*[:.,;-]?\s*/, '')
    .replace(/\s*\((?:CF|CC)-\d{3,5}\)/g, '')
    .trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Файлы, которые сделает фабрика (из dry-run): конфиг, позиция, оформление. */
export function filesOf(r: CreateResult | undefined) {
  const files = r?.files ?? [];
  const config = files.find((f) => /^channels\/[^/]+\.json$/.test(f.path)) ?? null;
  const stance = files.find((f) => f.path.endsWith('/stance.json')) ?? null;
  return { config, stance, all: files };
}

/** Черновик мастера сверх трёх входов — только то, что есть в шаблоне позиции. */
export type Draft = { thesis: string };

export const THESIS_PATH = ['position', 'thesis'] as const;

/** Пояснение поля позиции из самого файла (`thesis_note`), как у фабрики. */
export function thesisNote(stanceText: string | null | undefined): string | null {
  const doc = readDoc(stanceText ?? null);
  const n = valueAt(doc, ['position', 'thesis_note']);
  return typeof n === 'string' ? n : null;
}

/** Есть ли в позиции шаблона поле, которое правит мастер. */
export function hasThesis(stanceText: string | null | undefined): boolean {
  return typeof valueAt(readDoc(stanceText ?? null), [...THESIS_PATH]) === 'string';
}

/**
 * Текст позиции с черновиком поверх `base` (файла, который сделала или сделает фабрика):
 * правка точечная, без переформатирования. null — менять нечего.
 */
export function draftStance(base: string | null | undefined, draft: Draft): string | null {
  if (!base || !hasThesis(base)) return null;
  const thesis = draft.thesis.trim();
  const now = valueAt(readDoc(base), [...THESIS_PATH]);
  if (thesis === now) return null;
  return setValue(base, [...THESIS_PATH], thesis);
}

export type DiffLine = { kind: ' ' | '+' | '-'; text: string };

/** Построчная разница двух текстов (LCS; файлы маленькие). */
export function lineDiff(a: string, b: string): DiffLine[] {
  const x = a.split('\n');
  const y = b.split('\n');
  const n = x.length;
  const m = y.length;
  const t: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      t[i]![j] = x[i] === y[j] ? t[i + 1]![j + 1]! + 1 : Math.max(t[i + 1]![j]!, t[i]![j + 1]!);
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      out.push({ kind: ' ', text: x[i]! });
      i++;
      j++;
    } else if (t[i + 1]![j]! >= t[i]![j + 1]!) out.push({ kind: '-', text: x[i++]! });
    else out.push({ kind: '+', text: y[j++]! });
  }
  while (i < n) out.push({ kind: '-', text: x[i++]! });
  while (j < m) out.push({ kind: '+', text: y[j++]! });
  return out;
}

/** Только изменённые строки и по одной строке вокруг — для «подробнее». */
export function diffHunks(lines: readonly DiffLine[], context = 1): DiffLine[] {
  const keep = new Set<number>();
  lines.forEach((l, i) => {
    if (l.kind === ' ') return;
    for (let k = i - context; k <= i + context; k++) keep.add(k);
  });
  return lines.filter((_, i) => keep.has(i));
}
