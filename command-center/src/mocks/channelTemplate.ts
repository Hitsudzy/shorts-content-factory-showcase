// Шаблон нового канала подставной фабрики — по форме как `shared/channel_template/` и
// `shared/new_channel.py` живой (CC-0008): три входа, три файла, заглушка без конвейера.
// Общий для Vitest и Playwright, поэтому импорты относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export const ID_PATTERN = '^[a-z](?:[a-z0-9]|-(?=[a-z0-9])){1,39}$';
export const LANGUAGE_PATTERN = '^[a-z]{2}(?:-[A-Z]{2})?$';
export const NAME_MAX = 60;
/** Имена, которые канал взять не может: маршруты API под /channels/ (`RESERVED_IDS` фабрики). */
export const RESERVED_IDS: readonly string[] = ['template', 'new'];
export const NO_PIPELINE_LINE = 'конвейера нет - батча не будет';
/** Дата `{{created}}` подставной фабрики — постоянная, чтобы снимки и тексты не плыли. */
export const CREATED = '2026-10-10';

export const TEMPLATE_INPUTS: S['TemplateInput'][] = [
  {
    name: 'channel_id',
    label: 'Идентификатор',
    required: true,
    default: null,
    pattern: ID_PATTERN,
    note: 'Имя файла channels/<id>.json и папки батчей pipeline/<id>/: латиница в нижнем регистре, цифры, дефис внутри, от 2 до 40 знаков, первая - буква. Не может быть именем другого канала, в том числе прежним (former_channel_ids). Потом не меняется: переименование - отдельная работа (CF-0197).',
  },
  {
    name: 'display_name',
    label: 'Название',
    required: true,
    default: null,
    pattern: null,
    note: `Как канал называется на YouTube и в центре (display_name), до ${NAME_MAX} знаков, одна строка; не название другого канала.`,
  },
  {
    name: 'language',
    label: 'Язык роликов',
    required: false,
    default: 'en',
    pattern: LANGUAGE_PATTERN,
    note: 'Код языка (language конфига): en, ru, de, pt-BR... Все каналы фабрики сейчас - en.',
  },
];

export const TEMPLATE_FILES: S['TemplateFile'][] = [
  { template: 'shared/channel_template/config.json', path: 'channels/{id}.json' },
  { template: 'shared/channel_template/stance.json', path: 'channels/{id}/stance.json' },
  {
    template: 'shared/channel_template/brand/description.md',
    path: 'channels/{id}/brand/description.md',
  },
];

const BATCH_SCHEDULE = {
  enabled: false,
  note: 'CC-0008: a new channel is created off the schedule - no pipeline, no run_plan, the daily batch never comes here. It is turned on when the channel has its run_plan.',
};

/** Конфиг шаблона с незаполненными `{{…}}` — как `config` в `GET /api/channels/template`. */
export const TEMPLATE_CONFIG: Record<string, unknown> = {
  channel_id: '{{channel_id}}',
  display_name: '{{display_name}}',
  theme: {
    bg: '#0E1116',
    accent: '#F2B33D',
    accent2: '#5B7CFA',
    text: '#F4F4F2',
    muted: '#A3A9B5',
    card_ground: ['#232A36', '#171C25', '#0E1116'],
    end_card_ground: ['#2A3240', '#1F2632', '#151A22'],
    picked: ['bg', 'accent', 'accent2', 'text', 'muted', 'card_ground', 'end_card_ground'],
    note: "CC-0008: the template's neutral palette (shared/channel_template/config.json), nobody's brand - every value is in `picked`. Replace it with the channel's brand palette (docs/channel-data.md «The theme»); the factory's contrast rules check it on every save.",
  },
  language: '{{language}}',
  status: 'no_pipeline',
  status_note:
    "CC-0008: created from the command center on {{created}} from the factory's template. A channel without a pipeline yet: no run_plan (the executor refuses it), no publisher (no slot, no queue), batch_schedule.enabled false (the factory's daily batch never goes here). Every reader of channels/*.json says «конвейера нет - батча не будет» for it. The blocks a pipeline reads - scope, sources, patterns, insert layers, voice, the lists in channels/{{channel_id}}/ (fact-sources, rights-holder-blacklist, footage-origin) - are added by editing this file; the status key goes away together with this note when the channel gets its run_plan.",
  batch_schedule: BATCH_SCHEDULE,
  stance: '{{channel_id}}/stance.json',
  stance_note:
    "CC-0008: the channel's position - the template's empty skeleton until a person writes it (channels/{{channel_id}}/stance.json).",
};

const TEMPLATE_STANCE: Record<string, unknown> = {
  channel_id: '{{channel_id}}',
  channel_id_note:
    'Matches channels/{{channel_id}}.json, which points here via its `stance` field.',
  decided_by: {
    task: null,
    date: null,
    note: "Nobody has decided this channel's position yet: the file is the empty skeleton of the factory's template, created from the command center on {{created}}.",
  },
  authorship: '',
  position: {
    thesis: '',
    thesis_note:
      "What every video of the channel does, in one sentence - the channel's frame. Written by a person (a grill), applied by the machine to every video.",
  },
  left_open: [
    'The whole position: the frame, what is out of it, the voice, what the fact is, the refusal, the declaration. A channel with a pipeline needs every part its consumers read; a channel without one does not yet.',
  ],
  note: "CC-0008: the template's skeleton. Fill it in from the command center's editor (the «Позиция» part of the channel).",
};

const TEMPLATE_BRAND = `# {{display_name}} — оформление канала в Studio

- **Название:** {{display_name}}
- **Хэндл:** не заведён
- **Аватар / баннер:** \`avatar.png\`, \`banner.png\` в этой папке — ещё не положены
- **Палитра роликов:** \`theme\` в \`channels/{{channel_id}}.json\` — сейчас нейтральная палитра шаблона, ждёт бренда

## Описание (вставлять как есть)

Не написано.
`;

type Values = { channel_id: string; display_name: string; language: string; created: string };

const fill = (s: string, v: Values) =>
  s.replace(/\{\{(\w+)\}\}/g, (m, k: string) => (k in v ? v[k as keyof Values] : m));

function walk(node: unknown, v: Values): unknown {
  if (typeof node === 'string') return fill(node, v);
  if (Array.isArray(node)) return node.map((x) => walk(x, v));
  if (node && typeof node === 'object')
    return Object.fromEntries(Object.entries(node).map(([k, x]) => [k, walk(x, v)]));
  return node;
}

/** Файлы нового канала, как их пишет фабрика: JSON — indent=2 с переводом строки в конце. */
export function renderChannel(values: Omit<Values, 'created'>): S['NewFile'][] {
  const v = { ...values, created: CREATED };
  const json = (doc: unknown) => `${JSON.stringify(walk(doc, v), null, 2)}\n`;
  const id = values.channel_id;
  return [
    { path: `channels/${id}.json`, text: json(TEMPLATE_CONFIG) },
    { path: `channels/${id}/stance.json`, text: json(TEMPLATE_STANCE) },
    { path: `channels/${id}/brand/description.md`, text: fill(TEMPLATE_BRAND, v) },
  ];
}

export const TEMPLATE_BASE: Omit<S['ChannelTemplate'], 'lock'> = {
  inputs: TEMPLATE_INPUTS,
  files: TEMPLATE_FILES,
  status: 'no_pipeline',
  no_pipeline: NO_PIPELINE_LINE,
  batch_schedule: BATCH_SCHEDULE,
  config: TEMPLATE_CONFIG,
};
