// Записи публикации без сети (CC-0065 фабрики, договор 0.19.0+; центр собран под 0.20.0):
// пауза канала (поставить с причиной и сроком, снять с заметкой), карточка ролика (разместить в
// слот — `publish_queue.plan_slot` со сдвигами и предупреждениями; собрать из готового черновика —
// карточка выходит не готовой, `claims_not_checked`; черновик моделью — отказ `model_refused`)
// и ротация (назначить пары, отклонить пару — в плане вердикт `rotate.rule_on_rejection`,
// отказаться за нехваткой материала — с файлом дефицита под `pipeline/`). Каждое — в два вызова,
// как у батчей (./batchActions): `…/<действие>/plan` ничего не пишет и при «можно» даёт токен
// на `expires_in_s` (120 с), `…/<действие>` берёт только `{confirm}`. Отказы —
// `PublishWriteProblem {message, code, details}`: разбирает `takeBatch` (./batchProblem), а
// словами для человека их называет `writeProblemText`.
//
// Подпись холда (CC-0070 фабрики, 0.22.0; экран — CC-0071): центр подписывает холд
// content-sensitivity от имени пользователя (`signature.via: center`), только если строка
// холда пришла с `signable: true`. План — `{note}` (заметка обязательна, иначе 422
// `empty_note`): что отметил compliance-checker (`flagged`), что значит подпись (`meaning`),
// токен; «да» — `{confirm}`, в ответе — подписанная строка и свежие холды канала.
//
// Записи, что выходят за машину (CC-0066 фабрики, 0.20.0; экран — CC-0069): переключатель
// API-загрузки (включение — с заметкой в плане и фразой `audit_phrase` в «да», иначе 422
// `audit_unconfirmed` и токен сгорел), загрузка на YouTube (план — сухой прогон `upload.py` со
// сводкой и условиями YouTube; «да» — `{confirm, answer}`, где `answer` пользователь набрал сам:
// не «да» — 422 `answer_required`, токен цел; загрузка идёт долго, ждём до `UPLOAD_TIMEOUT_MS`)
// и запись загрузки из Studio (план — расхождения Studio с карточкой и `would-add|exists`).
import { useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { NAMESAKES_TEXT, takeBatch } from './batchProblem';
import { api, type Schemas } from './client';
import { publishKeys } from './publish';

export type PublishWriteProblem = Schemas['PublishWriteProblem'];
export type PublishWriteCode = PublishWriteProblem['code'] | 'not_working_factory';
export type PausePlan = Schemas['PausePlan'];
export type PauseWriteResult = Schemas['PauseWriteResult'];
export type CardPlacePlan = Schemas['CardPlacePlan'];
export type CardPlaceResult = Schemas['CardPlaceResult'];
export type CardBuildPlan = Schemas['CardBuildPlan'];
export type CardBuildResult = Schemas['CardBuildResult'];
export type RotationPlan = Schemas['RotationPlan'];
export type RotationResult = Schemas['RotationResult'];
/** Поля со значением по умолчанию в договоре — необязательны и в теле центра. */
type Loose<T, K extends keyof T> = Omit<T, K> & Partial<Pick<T, K>>;
export type PauseSetPlanIn = Loose<Schemas['PauseSetPlanIn'], 'replace'>;
export type PauseClearPlanIn = Schemas['PauseClearPlanIn'];
export type CardPlacePlanIn = Loose<Schemas['CardPlacePlanIn'], 'replace'>;
export type CardBuildPlanIn = Loose<Schemas['CardBuildPlanIn'], 'model'>;
export type RotationAssignPlanIn = Loose<Schemas['RotationAssignPlanIn'], 'despite_shortage'>;
export type RotationRejectPlanIn = Loose<Schemas['RotationRejectPlanIn'], 'rejects_rhythm'>;
export type RotationRefusePlanIn = Schemas['RotationRefusePlanIn'];
export type SwitchPlanIn = Schemas['SwitchPlanIn'];
export type SwitchPlan = Schemas['SwitchPlan'];
export type SwitchResult = Schemas['SwitchResult'];
export type UploadPlanIn = Schemas['UploadPlanIn'];
export type UploadPlan = Schemas['UploadPlan'];
export type UploadResult = Schemas['UploadResult'];
export type StudioRecordPlanIn = Schemas['StudioRecordPlanIn'];
export type StudioRecordPlan = Schemas['StudioRecordPlan'];
export type StudioRecordResult = Schemas['StudioRecordResult'];
export type StudioEditedPlanIn = Schemas['StudioEditedPlanIn'];
export type StudioEditedPlan = Schemas['StudioEditedPlan'];
export type StudioEditedResult = Schemas['StudioEditedResult'];
export type HoldSignPlan = Schemas['HoldSignPlan'];
export type HoldSignResult = Schemas['HoldSignResult'];
/** Какой холд подписать: батч и тема строки холда (`hold_id` — `канал/батч/тема`). */
export type HoldTarget = { batch_id: string; topic_id: string };

/** Расхождение Studio с карточкой (`studio_fields.compare`): поле, ждали, Studio показывает. */
export type Mismatch = { field: string; expected?: unknown; read?: unknown };

/**
 * Сколько ждать ответа на «да» загрузки: `upload.py` держит запись, пока ролик уходит на
 * YouTube (возобновляемая загрузка, повторы). Окно всё это время ждёт и второй раз не шлёт.
 */
export const UPLOAD_TIMEOUT_MS = 20 * 60_000;

/** Сколько знаков фабрика ждёт от причины отказа от пары (`rotate.MIN_REASON_CHARS`). */
export const MIN_REASON_CHARS = 25;

/** Черновик карточки — то, что `publish_card.validate_draft` принимает. */
export type CardDraft = { title: string; about: string; hashtags: string[]; tags: string[] };

/** Слот из плана выкладки (`publish_queue.plan_slot`, как его отдаёт API). */
export type PlannedSlot = {
  slot: string | null;
  day: string | null;
  line: string | null;
  note: string | null;
  /** CC-0180: ближайший свободный слот дальше горизонта ленты: `slot` — null, ролик в копилке. */
  beyond_horizon?: boolean;
  warnings: string[];
  moves: {
    slug?: string;
    batch_id?: string;
    from?: string;
    slot?: string;
    day?: string;
    line?: string;
  }[];
};

/** Вердикт `rotate.rule_on_rejection`: `upheld` — отказ примут и дадут замену, `denied` — нет. */
export type Ruling = {
  verdict: 'upheld' | 'denied' | string;
  explanation?: string | null;
  replacement?: string[] | null;
  rule?: string | null;
  excluded_rhythm?: string | null;
};

/** Сценарий плана назначения: пара уже стоит, тема ждёт материала или пару вытянет ротация. */
export type AssignScript = {
  script_id: string;
  state: 'standing' | 'held' | 'fresh' | string;
  pattern_id?: string;
  rhythm_id?: string;
  seq?: number;
  retry_when?: string | null;
};

const ch = (channel: string) => ({ path: { channel } });

const call = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

// ---------------------------------------------------------------- пауза
export const planPauseSet = (channel: string, body: PauseSetPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/pause/set/plan', {
        params: ch(channel),
        body: { replace: false, ...body },
        signal,
      }),
    ),
  );

export const pauseSet = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/pause/set', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

export const planPauseClear = (channel: string, body: PauseClearPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/pause/clear/plan', {
        params: ch(channel),
        body,
        signal,
      }),
    ),
  );

export const pauseClear = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/pause/clear', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

// ---------------------------------------------------------------- карточка
export const planCardPlace = (channel: string, body: CardPlacePlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/card/place/plan', {
        params: ch(channel),
        body: { replace: false, ...body },
        signal,
      }),
    ),
  );

export const cardPlace = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/card/place', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

export const planCardBuild = (channel: string, body: CardBuildPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/card/build/plan', {
        params: ch(channel),
        body: { model: false, ...body },
        signal,
      }),
    ),
  );

export const cardBuild = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/card/build', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

// ---------------------------------------------------------------- ротация
export const planRotationAssign = (channel: string, body: RotationAssignPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/rotation/assign/plan', {
        params: ch(channel),
        body: { despite_shortage: false, ...body },
        signal,
      }),
    ),
  );

export const rotationAssign = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/rotation/assign', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

export const planRotationReject = (channel: string, body: RotationRejectPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/rotation/reject/plan', {
        params: ch(channel),
        body: { rejects_rhythm: false, ...body },
        signal,
      }),
    ),
  );

export const rotationReject = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/rotation/reject', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

export const planRotationRefuse = (channel: string, body: RotationRefusePlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/rotation/refuse/plan', {
        params: ch(channel),
        body,
        signal,
      }),
    ),
  );

export const rotationRefuse = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/rotation/refuse', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

// ---------------------------------------------------------------- переключатель API-загрузки
export const planApiSwitch = (channel: string, body: SwitchPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/api-upload/switch/plan', {
        params: ch(channel),
        body,
        signal,
      }),
    ),
  );

/** `audit` — фраза, которую пользователь набрал сам; при выключении не нужна. */
export const apiSwitch = (channel: string, confirm: string, audit: string | null) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/api-upload/switch', {
        params: ch(channel),
        body: audit == null ? { confirm } : { confirm, audit },
        signal,
      }),
    ),
  );

// ---------------------------------------------------------------- загрузка на YouTube
export const planUpload = (channel: string, body: UploadPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/upload/plan', {
        params: ch(channel),
        body,
        signal,
      }),
    ),
  );

/** `answer` — ровно то, что набрал пользователь: центр «да» не подставляет. */
export const upload = (channel: string, confirm: string, answer: string, ms = UPLOAD_TIMEOUT_MS) =>
  within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/upload', {
        params: ch(channel),
        body: { confirm, answer },
        signal,
      }),
    ),
  );

// ---------------------------------------------------------------- запись загрузки из Studio
export const planStudioRecord = (channel: string, body: StudioRecordPlanIn) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/studio/record/plan', {
        params: ch(channel),
        body,
        signal,
      }),
    ),
  );

export const studioRecord = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/studio/record', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

// ---------------------------------------------------------------- ручная правка в Studio
// CC-0106: «правил в Studio руками» — отметка на строке журнала загрузок (серия без правок
// начинается заново), и её отмена, если отметка ошибочна. План — сухой прогон фабрики; «да» —
// только `{confirm}` (набранное «да» — условие центра, фабрике его не шлём).
export const planStudioEdited = (channel: string, body: StudioEditedPlanIn, undo = false) =>
  call(async (signal) =>
    takeBatch(
      undo
        ? await api.POST('/api/publish/{channel}/studio/edited/undo/plan', {
            params: ch(channel),
            body,
            signal,
          })
        : await api.POST('/api/publish/{channel}/studio/edited/plan', {
            params: ch(channel),
            body,
            signal,
          }),
    ),
  );

export const studioEdited = (channel: string, confirm: string, undo = false) =>
  call(async (signal) =>
    takeBatch(
      undo
        ? await api.POST('/api/publish/{channel}/studio/edited/undo', {
            params: ch(channel),
            body: { confirm },
            signal,
          })
        : await api.POST('/api/publish/{channel}/studio/edited', {
            params: ch(channel),
            body: { confirm },
            signal,
          }),
    ),
  );

/**
 * Почему отметку поставить нельзя — словами. Строки `JournalError` фабрики английские (как их
 * пишет `upload_records`): известные — по-русски, прочие — как есть.
 */
export function editedWhy(why: string | null | undefined): string | null {
  if (!why) return null;
  if (/^no journal row for /.test(why)) return 'Такого ролика нет в журнале загрузок.';
  if (/live rows/.test(why))
    return 'Под этим именем в журнале несколько роликов — укажите ссылку на нужный.';
  if (/only the Studio path/.test(why))
    return 'Ролик загружен не через Studio — серию без правок он не считает.';
  if (/^name the video/.test(why)) return 'Укажите ролик: ссылку на него или его id в Studio.';
  return why;
}

// ---------------------------------------------------------------- подпись холда
const holdOf = (channel: string, h: HoldTarget) => ({
  path: { channel, batch_id: h.batch_id, topic_id: h.topic_id },
});

/** План подписи: `note` — почему ролик можно публиковать (обязательна, без пробелов по краям). */
export const planHoldSign = (channel: string, hold: HoldTarget, note: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/holds/{batch_id}/{topic_id}/sign/plan', {
        params: holdOf(channel, hold),
        body: { note },
        signal,
      }),
    ),
  );

export const holdSign = (channel: string, hold: HoldTarget, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/holds/{batch_id}/{topic_id}/sign', {
        params: holdOf(channel, hold),
        body: { confirm },
        signal,
      }),
    ),
  );

/** Id ролика из того, что показывает Studio: сам id (11 знаков) или ссылка на ролик. */
export function videoIdOf(text: string): string | null {
  const t = text.trim();
  if (!t) return null;
  const m = /(?:shorts\/|youtu\.be\/|[?&]v=|\/video\/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])/.exec(t);
  if (m) return m[1]!;
  return /^[A-Za-z0-9_-]{11}$/.test(t) ? t : null;
}

/** Поля, прочитанные со страницы Studio после сохранения, — как их ждёт `studio_fields`. */
export type StudioReadForm = {
  title: string;
  description: string;
  tags: string;
  visibility: string;
  publishAt: string;
};

/**
 * Прочитанное из Studio → `read` плана: JSON целиком (как его пишет `studio_fields.py read`)
 * или поля формы. `{read}` либо `{why}` — почему не взять.
 */
export function studioReadOf(
  form: StudioReadForm,
  json: string,
): { read: Record<string, unknown>; why?: undefined } | { read?: undefined; why: string } {
  if (json.trim()) {
    let v: unknown;
    try {
      v = JSON.parse(json);
    } catch {
      return { why: 'Прочитанное из Studio не читается как JSON.' };
    }
    if (!v || typeof v !== 'object' || Array.isArray(v))
      return { why: 'Прочитанное из Studio — объект JSON {title, description, tags, …}.' };
    return { read: v as Record<string, unknown> };
  }
  if (!form.title.trim()) return { why: 'Впишите название, как его показывает Studio.' };
  if (!form.publishAt.trim())
    return { why: 'Впишите время публикации, как его показывает Studio.' };
  return {
    read: {
      title: form.title,
      description: form.description,
      tags: listOf(form.tags),
      visibility: form.visibility.trim(),
      publish_at: form.publishAt.trim(),
    },
  };
}

// ---------------------------------------------------------------- разбор и слова
/** Отказ фабрики словами — заголовок над её строкой (строка — как есть, код — в «подробнее»). */
export const WRITE_PROBLEM_TEXT: Record<string, string> = {
  not_working_factory: 'Только смотреть: записи делает только API на рабочей фабрике',
  confirm_unknown: 'Подтверждение не найдено или уже использовано — нужен новый план',
  confirm_expired: 'План устарел — запросите заново: подтверждение живёт две минуты',
  confirm_mismatch: 'Подтверждение было выдано другому действию и сгорело — нужен новый план',
  check_changed: 'С момента плана что-то изменилось — посмотрите план заново',
  refused: 'Фабрика отказала',
  busy: 'Идёт другая запись публикации — подождите и нажмите ещё раз',
  invalid: 'Фабрика не приняла введённое — поправьте поля',
  note_required: 'Нужна причина',
  rotation_broken: 'Ротация канала не читается: нет её настроек или журнал повреждён',
  model_refused: 'Черновик моделью из центра не пишется',
  factory_broken:
    'Фабрика сломалась посреди записи — сначала посмотрите состояние, потом повторяйте',
  unknown_channel: 'Такого канала нет',
  unknown_batch: 'Такого батча нет',
  unknown_video: 'Такого ролика в батче нет',
  pause_unreadable: 'Реестр пауз не читается',
  card_broken: 'Карточка не читается',
  audit_unconfirmed: 'Фраза аудита не совпала — переключатель не тронут, нужен новый план',
  switch_unreadable: 'Файл переключателя API-загрузки не читается',
  answer_required: 'Загрузка — только после вашего «да»',
  unknown_note: 'Такой заметки к публикации нет',
  namesakes: NAMESAKES_TEXT,
  reauthorize: 'Токен YouTube надо переразрешить — ничего не загружено',
  upload_failed: 'YouTube не принял загрузку',
  uploaded_unrecorded: 'Ролик загружен, но запись о загрузке не легла — внесите её руками',
  no_such_hold: 'Такого холда нет',
  already_signed: 'Холд уже подписан',
  already_resolved: 'Холд уже снят',
  not_signable: 'Этот холд центр не снимает',
  empty_user: 'Не записано, кто подписывает',
  empty_note: 'Нужна заметка: почему ролик можно публиковать',
  ledger_unreadable: 'Реестр холдов не читается',
  holds_unreadable: 'Реестр холдов не читается',
  journal_unreadable: 'Журнал загрузок не читается',
};

export const writeProblemText = (code: string | null | undefined): string =>
  (code && WRITE_PROBLEM_TEXT[code]) || 'Фабрика отказала';

/** «тег1, тег2» / «#a #b» → список без пустых и повторов (решётку фабрика ставит сама). */
export function listOf(text: string, hash = false): string[] {
  const out: string[] = [];
  for (const raw of text.split(hash ? /[\s,]+/ : /,/)) {
    const v = (hash ? raw.replace(/^#+/, '') : raw).trim();
    if (v && !out.includes(v)) out.push(v);
  }
  return out;
}

/** «a1 a2, a3» → id сценариев. */
export const idsOf = (text: string) => listOf(text.replace(/\s+/g, ','));

/** «example-film/2026-10-09T0200Z» или «2026-10-09T0200Z» → поля тела карточки. */
export function batchOf(text: string): { batch_id: string; dir: string | null } | null {
  const t = text.trim().replace(/^\/+|\/+$/g, '');
  if (!t) return null;
  const parts = t.split('/');
  if (parts.length === 1) return { batch_id: parts[0]!, dir: null };
  if (parts.length === 2 && parts[0] && parts[1]) return { batch_id: parts[1], dir: parts[0] };
  return null;
}

/** Файл дефицита — под `pipeline/` и без `..`: иначе фабрика откажет `invalid`. */
export function deficitWhy(path: string): string | null {
  const parts = path.trim().split('/').filter(Boolean);
  if (!parts.length) return 'Укажите файл дефицита батча (под pipeline/).';
  if (parts[0] !== 'pipeline' || parts.some((p) => p === '.' || p === '..'))
    return 'Файл дефицита — только под pipeline/ (план батча plan.assetless-rung.json).';
  return null;
}

/** После любой записи публикации перечитать всё, что про неё показано на экране. */
export function useAfterPublishWrite() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: publishKeys.all });
}
