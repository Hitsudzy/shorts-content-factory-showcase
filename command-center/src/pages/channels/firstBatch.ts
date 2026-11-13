// «Что ещё нужно до первого батча» — из заметок самих файлов нового канала (шаблон фабрики).
// Отдельного списка у фабрики нет: здесь только то, что говорят её `status`/`*_note`,
// `batch_schedule`, `theme.picked` и пустая позиция. Ничего сверх этого не обещаем.
import { valueAt } from './fields';
import { stripTasks } from './wizard';

export type TodoItem = {
  id: string;
  title: string;
  text: string;
  /** Пояснение фабрики как есть и ключи конфига — под «подробнее». */
  more: string[];
};

/** Блоки, которые читает конвейер (их перечисляет `status_note` шаблона), — по-человечески. */
const PIPELINE_BLOCKS: [key: string, human: string][] = [
  ['scope', 'тематика (что брать в батч)'],
  ['sources', 'источники'],
  ['patterns', 'паттерны роликов'],
  ['insert_layers', 'слои вставок'],
  ['voice_profile', 'голос озвучки'],
];

type Doc = Record<string, unknown> | null;

const str = (v: unknown) => (typeof v === 'string' ? v : null);

export function todoItems(
  config: Doc,
  stance: Doc,
  noPipeline: string | null,
  brand: string | null = null,
): TodoItem[] {
  const out: TodoItem[] = [];
  if (!config) return out;
  const statusNote = str(config.status_note);
  if (config.status === 'no_pipeline' || noPipeline) {
    out.push({
      id: 'pipeline',
      title: 'Конвейер',
      text: `${noPipeline ?? 'Конвейера нет — батча не будет'}. У канала нет плана прогона, и исполнитель батчей его не берёт; публикатора тоже нет — ни слота, ни очереди. Конвейер каналу подключают отдельной работой.`,
      more: [
        'status: no_pipeline',
        'нет run_plan и publisher',
        ...(statusNote ? [statusNote] : []),
      ],
    });
  }
  const bs = valueAt(config, ['batch_schedule']);
  if (valueAt(bs, ['enabled']) === false) {
    const note = str(valueAt(bs, ['note']));
    out.push({
      id: 'schedule',
      title: 'Расписание батчей',
      text: 'Канал выключен из расписания: ежедневный батч фабрики к нему не придёт. Включается, когда у канала появится план прогона.',
      more: ['batch_schedule.enabled: false', ...(note ? [note] : [])],
    });
  }
  const missing = PIPELINE_BLOCKS.filter(([k]) => !(k in config));
  if (missing.length) {
    out.push({
      id: 'blocks',
      title: 'Настройки конвейера',
      text: `В конфиге пока нет того, что читает конвейер: ${missing.map(([, h]) => h).join(', ')}; ещё — списки канала (источники фактов, правообладатели, происхождение футажа). Всё это добавляется правкой канала в редакторе.`,
      more: [`нет ключей: ${missing.map(([k]) => k).join(', ')}`],
    });
  }
  const picked = valueAt(config, ['theme', 'picked']);
  if (Array.isArray(picked) && picked.length) {
    const note = str(valueAt(config, ['theme', 'note']));
    out.push({
      id: 'theme',
      title: 'Палитра роликов',
      text: 'Сейчас — нейтральная палитра шаблона, не бренд канала. Её заменяют палитрой бренда; контраст цветов фабрика проверяет при каждом сохранении.',
      more: [`theme.picked: ${picked.join(', ')}`, ...(note ? [stripTasks(note)] : [])],
    });
  }
  if (stance) {
    const thesis = str(valueAt(stance, ['position', 'thesis']));
    const open = valueAt(stance, ['left_open']);
    const openText = Array.isArray(open) ? open.filter((x) => typeof x === 'string') : [];
    out.push({
      id: 'stance',
      title: 'Позиция канала',
      text: thesis
        ? 'Записана позиция в одну фразу. Остальное — что вне рамки, голос, что считать фактом, отказ, декларация — ещё открыто; это пишет человек в «Позиции» канала.'
        : 'Позиция пуста: заготовка шаблона. Её пишет человек — в редакторе канала, часть «Позиция».',
      more: openText as string[],
    });
  }
  if (brand) {
    out.push({
      id: 'brand',
      title: 'Оформление в YouTube Studio',
      text: 'Заготовка: описание канала и ключевые слова не написаны, аватар и баннер не положены, хэндл не заведён.',
      more: [],
    });
  }
  return out;
}

/** С чем мастер привёл человека в редактор нового канала (состояние перехода роутера). */
export type WizardLanding = {
  /** Тема коммита создания (один коммит: конфиг, позиция, оформление). */
  created: string;
  /** Позиция — с фразой из мастера (`stance_text` в том же коммите). */
  withStance: boolean;
};

export function landingOf(state: unknown): WizardLanding | null {
  const w = (state as { wizard?: WizardLanding } | null)?.wizard;
  return w && typeof w.created === 'string' ? w : null;
}
