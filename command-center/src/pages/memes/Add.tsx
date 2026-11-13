// «Добавить мем» на столе (CC-0133 → CC-0076 API): картинка по ссылке, GIF из видео (отрезок по
// секундам) и контактный лист кадров видео. Каждое — как вырезка фона: поля → план фабрики без
// сети (что скачается, куда ляжет, худшее время) → «да» с отсчётом → фоновая задача, её ход и
// итог — блок задачи на столе (./Job.tsx): новая запись `pending` в сетке или лист кадров
// картинкой с метками смен сцен. По листу человек отмечает два кадра — начало и конец гифки — и
// переносит отрезок в «GIF из видео». Ссылки — только http(s): центр подсказывает это до плана,
// решает API (`bad_url`). Отказы — словами фабрики, коды — под «подробнее».
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import {
  addResult,
  isHttpUrl,
  MAX_SHEET_FRAMES,
  MEME_ID_RE,
  planAddGif,
  planAddImage,
  planSheet,
  seconds,
  SHEET_COLS,
  sheetFrames,
  sheetParams,
  sheetResult,
  startAddGif,
  startAddImage,
  startSheet,
  tagsOf,
  type AddGifBody,
  type AddImageBody,
  type EmbeddingOutcome,
  type MemeAddGifPlan,
  type MemeAddImagePlan,
  type MemeSheetPlan,
  type SheetBody,
} from '@/api/memeAdds';
import { memeJobProblemText, type MemeJob, type MemeJobStarted } from '@/api/memeJobs';
import { nbDashes } from '@/api/humanText';
import { NO_REASON_TEXT } from '@/api/reasonRu';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { inputBase } from '@/pages/channels/styles';
import { PlanHead, WriteAction } from '@/pages/publishing/Writes';

import { memeName, sec } from './format';
import { hasCyrillic, namesIn } from './jobs';

const NB = ' ';

export type AddTab = 'image' | 'gif' | 'sheet';
/** Отрезок с листа кадров → поля «GIF из видео»; `n` — чтобы тот же отрезок лёг ещё раз. */
export type GifSeed = { video: string; start: number; end: number; n: number };

const TABS: { id: AddTab; label: string; tip: string }[] = [
  {
    id: 'image',
    label: 'Картинка по ссылке',
    tip: 'Картинка из интернета: файл .png, .jpg, .webp',
  },
  { id: 'gif', label: 'GIF из видео', tip: 'Беззвучная гифка из отрезка видео по ссылке' },
  {
    id: 'sheet',
    label: 'Лист кадров',
    tip: 'Кадры видео с метками времени и сменами сцен — чтобы выбрать отрезок для гифки',
  },
];

const ADD_PANEL = 'meme-add-panel';

/** Кнопка «Добавить мем» в строке поиска стола: раскрывает панель под строкой. */
export function AddToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <Tip content="Новый мем в банк по ссылке и лист кадров видео: сначала план фабрики" wide>
      <Button
        size="sm"
        variant="outline"
        aria-expanded={open}
        aria-controls={ADD_PANEL}
        data-testid="meme-add-toggle"
        onClick={onToggle}
        className="max-sm:flex-1"
      >
        Добавить мем
        <span aria-hidden>{open ? '▴' : '▾'}</span>
      </Button>
    </Tip>
  );
}

// ---- поля

function Field({
  label,
  tip,
  hint,
  bad,
  children,
  className,
}: {
  label: string;
  tip?: string;
  /** Подсказка под полем, когда в нём что-то не так (решает всё равно фабрика). */
  hint?: string | null;
  bad?: boolean;
  children: (id: string, describedBy: string | undefined) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className={cn('grid min-w-0 content-start gap-1', className)}>
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {tip ? (
          <Tip content={tip} wide>
            <span className="cursor-help underline decoration-dotted underline-offset-2">
              {label}
            </span>
          </Tip>
        ) : (
          label
        )}
      </label>
      {children(id, bad && hint ? hintId : undefined)}
      {bad && hint ? (
        <span id={hintId} className="text-xs text-danger" data-testid="field-hint">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

function Text({
  value,
  onChange,
  testId,
  placeholder,
  url = false,
  num = false,
  bad = false,
  multiline = false,
  ...field
}: {
  value: string;
  onChange: (v: string) => void;
  testId: string;
  placeholder?: string;
  url?: boolean;
  num?: boolean;
  bad?: boolean;
  multiline?: boolean;
  id: string;
  describedBy: string | undefined;
}) {
  const common = {
    id: field.id,
    value,
    'data-testid': testId,
    placeholder,
    'aria-invalid': bad || undefined,
    'aria-describedby': field.describedBy,
    className: inputBase,
  };
  if (multiline)
    return <textarea {...common} rows={2} onChange={(e) => onChange(e.target.value)} />;
  return (
    <input
      {...common}
      type={url ? 'url' : 'text'}
      inputMode={url ? 'url' : num ? 'decimal' : undefined}
      autoComplete="off"
      spellCheck={url || num ? false : undefined}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

const URL_HINT = `Только ссылка http(s)://…${NB}— локальный путь и file:// фабрика не берёт`;
const ID_HINT = 'Строчные латинские буквы, цифры, дефис и подчёркивание: dog-turns-around';
const ID_WORD = 'Короткое имя мема';

/** Первая причина, почему план не спросить (подсказка на погашенной кнопке). */
const first = (...why: (string | false | null | undefined)[]) =>
  why.find((w): w is string => !!w) ?? null;

const urlBad = (v: string) => !!v.trim() && !isHttpUrl(v);
const idBad = (v: string) => !!v.trim() && !MEME_ID_RE.test(v.trim());

function MemeFields({
  f,
  set,
  prefix,
}: {
  f: { id: string; description: string; tags: string };
  set: (k: 'id' | 'description' | 'tags', v: string) => void;
  prefix: string;
}) {
  return (
    <>
      <Field
        label="Короткое имя мема (латиницей)"
        tip="Под этим именем мем ляжет в банк, так же назовётся его файл: строчные латинские буквы, цифры, дефис"
        hint={ID_HINT}
        bad={idBad(f.id)}
      >
        {(id, d) => (
          <Text
            id={id}
            describedBy={d}
            value={f.id}
            onChange={(v) => set('id', v)}
            testId={`${prefix}-id`}
            placeholder="dog-turns-around"
            bad={idBad(f.id)}
          />
        )}
      </Field>
      <Field label="Теги" tip="Через запятую: по ним мем ищут на столе и подбирают к роликам">
        {(id, d) => (
          <Text
            id={id}
            describedBy={d}
            value={f.tags}
            onChange={(v) => set('tags', v)}
            testId={`${prefix}-tags`}
            placeholder="удивление, реакция"
          />
        )}
      </Field>
      <Field
        label="Описание"
        tip="Что на меме и когда он к месту — по описанию его подбирают к ролику"
        className="sm:col-span-2"
      >
        {(id, d) => (
          <Text
            id={id}
            describedBy={d}
            value={f.description}
            onChange={(v) => set('description', v)}
            testId={`${prefix}-description`}
            placeholder="Собака резко оборачивается на звук"
            multiline
          />
        )}
      </Field>
    </>
  );
}

const memeWhy = (f: { id: string; description: string }) =>
  first(
    !f.id.trim() && 'Придумайте короткое имя мема латиницей',
    idBad(f.id) && `${ID_WORD}: ${ID_HINT.toLowerCase()}`,
    !f.description.trim() && 'Опишите мем: что на нём и когда он к месту',
  );

// ---- план фабрики

type AnyPlan = MemeAddImagePlan | MemeAddGifPlan | MemeSheetPlan;

const STEP_NAMES: Record<string, string> = {
  download: 'скачать',
  check: 'проверить файл',
  index: 'записать в банк',
  embedding: 'пересчитать признаки для поиска похожих',
  scenes: 'найти смены сцен',
  cut: 'нарезать GIF',
  frames: 'извлечь кадры',
  sheet: 'склеить лист',
};

function Fact({
  label,
  children,
  testId,
}: {
  label: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[9rem_1fr] sm:gap-2" data-testid={testId}>
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 [overflow-wrap:anywhere]">{children}</span>
    </div>
  );
}

const span = (p: AnyPlan) => {
  const s = p.span as { start_s?: number; end_s?: number | null } | null | undefined;
  return s && typeof s.start_s === 'number' ? s : null;
};

const baseName = (f: string | null | undefined) => (f ? (f.split('/').pop() ?? f) : null);

/** Что план говорит о задаче: что скачается, куда ляжет, шаги и худшее время, заметки фабрики. */
export function AddPlanView({
  plan,
  yes,
  no,
  ids = [],
}: {
  plan: AnyPlan;
  yes: string;
  no: string;
  ids?: string[];
}) {
  const s = span(plan);
  const sheet = plan.action === 'meme_sheet' ? (plan as MemeSheetPlan) : null;
  const cached = 'cached' in plan && plan.cached;
  const every = (plan.span as { every_s?: number } | null)?.every_s;
  const frames = (plan.span as { frames?: number | null } | null)?.frames;
  return (
    <>
      <PlanHead plan={plan} yes={yes} no={no} />
      <div className="grid gap-1.5" data-testid="add-plan-facts">
        <Fact label="Что скачается" testId="add-plan-fetch">
          {plan.will_fetch === 'url'
            ? `картинка ${plan.url ?? ''}`
            : cached
              ? `ничего${NB}— видео уже скачано`
              : `видео ${plan.video ?? ''} (только картинка, до 720p)`}
        </Fact>
        {sheet ? (
          <Fact label="Куда" testId="add-plan-where">
            в папку листов кадров банка, файл {baseName(sheet.file)}
            {sheet.overwrites ? (
              <b className="block font-semibold text-warning" data-testid="add-plan-overwrites">
                Лист с таким именем уже есть{NB}— фабрика его перезапишет
              </b>
            ) : null}
          </Fact>
        ) : (
          <Fact label="Куда" testId="add-plan-where">
            в банк новым мемом {plan.id ? `«${memeName(plan.id)}»` : ''}, ждёт разбора
          </Fact>
        )}
        {s ? (
          <Fact label="Отрезок" testId="add-plan-span">
            {sec(s.start_s!)}–{typeof s.end_s === 'number' ? `${sec(s.end_s)} с` : 'конец видео'}
            {typeof s.end_s === 'number' && !sheet ? ` (${sec(s.end_s - s.start_s!)} с)` : ''}
            {sheet && every ? `, кадр каждые ${sec(every)} с` : ''}
            {sheet ? (typeof frames === 'number' ? `${NB}— ${frames} кадров` : '') : ''}
          </Fact>
        ) : null}
        {plan.tags?.length ? <Fact label="Теги">{plan.tags.join(', ')}</Fact> : null}
        <Fact label="Шаги">{plan.steps.map((x) => STEP_NAMES[x] ?? x).join(' → ')}</Fact>
        <Fact label="Предел времени" testId="add-plan-time">
          <Tip content="Сумма предельных времён всех шагов: дольше — значит, задача зависла" wide>
            <span className="cursor-help underline decoration-dotted underline-offset-2">
              {plan.max_seconds_word}
            </span>
          </Tip>
        </Fact>
      </div>
      <PlanNotes notes={plan.notes} ids={ids} />
      <More className="mt-0">
        <span>
          {plan.action} · {plan.kind} · банк {plan.bank}
        </span>
        <span>параметры: {JSON.stringify(plan.params)}</span>
        {plan.file ? <span>файл: {plan.file}</span> : null}
        {sheet ? <span>лист: {sheet.sheet}</span> : null}
        {plan.source_url ? <span>источник: {plan.source_url}</span> : null}
        <span>
          скачивание: {plan.will_fetch} · худшее время: {plan.max_seconds} с
        </span>
        {plan.job ? <span>идёт задача: {plan.job.job_id}</span> : null}
        {plan.machine_job ? (
          <span>
            задача на машине: {plan.machine_job.job_id} · банк {plan.machine_job.bank}
          </span>
        ) : null}
        <span>отпечаток плана: {plan.fingerprint}</span>
      </More>
    </>
  );
}

/** Заметки плана — простым русским фабрики (CC-0134), id мемов — именами. */
export function PlanNotes({ notes, ids = [] }: { notes: string[]; ids?: string[] }) {
  if (!notes.length) return null;
  return (
    <ul
      className="m-0 grid list-disc gap-0.5 pl-5 text-xs text-muted-foreground [overflow-wrap:anywhere]"
      data-testid="plan-notes"
    >
      {notes.map((n) => (
        <li key={n}>{nbDashes(namesIn(n, ids))}</li>
      ))}
    </ul>
  );
}

// ---- формы

type Started = (s: MemeJobStarted) => void;

type FormProps = {
  channel: string;
  bankLabel: string;
  ids: string[];
  busy: string | null;
  onStarted: Started;
  onSettled: () => void;
};

const say = (ids: string[]) => (t: string) => namesIn(t, ids);

function ImageForm({ channel, bankLabel, ids, busy, onStarted, onSettled }: FormProps) {
  const [f, setF] = useState({ url: '', source: '', id: '', description: '', tags: '' });
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  const why = first(
    !f.url.trim() && 'Вставьте ссылку на файл картинки',
    urlBad(f.url) && `Ссылка на картинку: ${URL_HINT.toLowerCase()}`,
    !f.source.trim() && 'Вставьте ссылку на страницу, где картинка найдена',
    urlBad(f.source) && `Ссылка на страницу: ${URL_HINT.toLowerCase()}`,
    memeWhy(f),
  );
  const body: AddImageBody | null = why
    ? null
    : {
        id: f.id.trim(),
        url: f.url.trim(),
        source_url: f.source.trim(),
        description: f.description.trim(),
        tags: tagsOf(f.tags),
      };
  return (
    <div className="grid gap-3" data-testid="meme-add-image">
      <p className="m-0 text-muted-foreground">
        Фабрика скачает картинку по ссылке (до 25 МБ), срежет пустую полосу подписи, если она есть,
        и положит мем в банк{NB}— он будет ждать разбора на столе.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Ссылка на картинку"
          tip="Прямая ссылка на файл .png, .jpg, .jpeg или .webp; GIF добавляется из видео"
          hint={URL_HINT}
          bad={urlBad(f.url)}
        >
          {(id, d) => (
            <Text
              id={id}
              describedBy={d}
              value={f.url}
              onChange={(v) => set('url', v)}
              testId="add-image-url"
              placeholder="https://i.imgflip.com/….jpg"
              url
              bad={urlBad(f.url)}
            />
          )}
        </Field>
        <Field
          label="Источник"
          tip="Страница, где картинка найдена: фабрика хранит её вместе с мемом"
          hint={URL_HINT}
          bad={urlBad(f.source)}
        >
          {(id, d) => (
            <Text
              id={id}
              describedBy={d}
              value={f.source}
              onChange={(v) => set('source', v)}
              testId="add-image-source"
              placeholder="https://imgflip.com/…"
              url
              bad={urlBad(f.source)}
            />
          )}
        </Field>
        <MemeFields f={f} set={set} prefix="add-image" />
      </div>
      <div>
        <WriteAction<AddImageBody, MemeAddImagePlan, MemeJobStarted>
          id="meme-add-image"
          label="Добавить картинку…"
          title={`Добавить картинку в банк ${bankLabel}?`}
          description={`Фабрика проверила без скачивания, что сделает. Добавление пойдёт в фоне${NB}— его ход виден на столе.`}
          body={body}
          why={busy ?? why}
          tip="Фабрика покажет план; картинка скачается после вашего «да»"
          confirmLabel="Добавить"
          pendingLabel="Запускаю…"
          plan={(b) => planAddImage(channel, b)}
          act={(confirm) => startAddImage(channel, confirm)}
          view={(p) => <AddPlanView plan={p} yes="можно добавить" no="добавить нельзя" ids={ids} />}
          problemText={memeJobProblemText}
          problemSay={say(ids)}
          onSettled={onSettled}
          onDone={onStarted}
        />
      </div>
    </div>
  );
}

function GifForm({
  channel,
  bankLabel,
  ids,
  busy,
  onStarted,
  onSettled,
  seed,
  onSheet,
}: FormProps & { seed: GifSeed | null; onSheet: () => void }) {
  const [f, setF] = useState(() => ({
    video: seed?.video ?? '',
    start: seed ? sec(seed.start) : '',
    end: seed ? sec(seed.end) : '',
    id: '',
    description: '',
    tags: '',
    source: '',
  }));
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  const start = seconds(f.start);
  const end = seconds(f.end);
  const spanBad = start !== null && end !== null && (start < 0 || end <= start);
  const why = first(
    !f.video.trim() && 'Вставьте ссылку на видео',
    urlBad(f.video) && `Ссылка на видео: ${URL_HINT.toLowerCase()}`,
    (start === null || end === null) && 'Задайте начало и конец отрезка в секундах',
    spanBad && 'Конец отрезка должен быть позже начала',
    urlBad(f.source) && `Ссылка на источник: ${URL_HINT.toLowerCase()}`,
    memeWhy(f),
  );
  const body: AddGifBody | null = why
    ? null
    : {
        id: f.id.trim(),
        video: f.video.trim(),
        start: start!,
        end: end!,
        description: f.description.trim(),
        tags: tagsOf(f.tags),
        ...(f.source.trim() ? { source_url: f.source.trim() } : {}),
      };
  return (
    <div className="grid gap-3" data-testid="meme-add-gif">
      <p className="m-0 text-muted-foreground">
        Фабрика возьмёт видео по ссылке (скачает один раз — для листа и для гифки), нарежет из
        отрезка беззвучную гифку и положит её в банк{NB}— она будет ждать разбора.{' '}
        <button
          type="button"
          className="text-primary-text underline underline-offset-2"
          onClick={onSheet}
          data-testid="add-gif-to-sheet"
        >
          Отрезок удобно выбрать по листу кадров
        </button>
        .
      </p>
      {seed ? (
        <p className="m-0 text-xs" role="status" data-testid="add-gif-seeded">
          Отрезок {sec(seed.start)}–{sec(seed.end)} с перенесён с листа кадров.
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Ссылка на видео"
          tip="Страница видео (YouTube и т.п.) или прямая ссылка на файл"
          hint={URL_HINT}
          bad={urlBad(f.video)}
          className="sm:col-span-2"
        >
          {(id, d) => (
            <Text
              id={id}
              describedBy={d}
              value={f.video}
              onChange={(v) => set('video', v)}
              testId="add-gif-video"
              placeholder="https://www.youtube.com/watch?v=…"
              url
              bad={urlBad(f.video)}
            />
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3 sm:col-span-2 sm:max-w-80">
          <Field label="Начало, с" hint="Конец должен быть позже начала" bad={spanBad}>
            {(id, d) => (
              <Text
                id={id}
                describedBy={d}
                value={f.start}
                onChange={(v) => set('start', v)}
                testId="add-gif-start"
                placeholder="12,4"
                num
                bad={spanBad}
              />
            )}
          </Field>
          <Field label="Конец, с">
            {(id, d) => (
              <Text
                id={id}
                describedBy={d}
                value={f.end}
                onChange={(v) => set('end', v)}
                testId="add-gif-end"
                placeholder="15"
                num
                bad={spanBad}
              />
            )}
          </Field>
        </div>
        <MemeFields f={f} set={set} prefix="add-gif" />
        <Field
          label="Источник (если не само видео)"
          tip="Страница, откуда видео; пусто — источником будет сама ссылка на видео"
          hint={URL_HINT}
          bad={urlBad(f.source)}
          className="sm:col-span-2"
        >
          {(id, d) => (
            <Text
              id={id}
              describedBy={d}
              value={f.source}
              onChange={(v) => set('source', v)}
              testId="add-gif-source"
              placeholder="https://…"
              url
              bad={urlBad(f.source)}
            />
          )}
        </Field>
      </div>
      <div>
        <WriteAction<AddGifBody, MemeAddGifPlan, MemeJobStarted>
          id="meme-add-gif"
          label="Сделать GIF…"
          title={`Сделать GIF в банк ${bankLabel}?`}
          description={`Фабрика проверила без скачивания, что сделает. Нарезка пойдёт в фоне${NB}— её ход виден на столе.`}
          body={body}
          why={busy ?? why}
          tip="Фабрика покажет план; видео скачается после вашего «да»"
          confirmLabel="Сделать GIF"
          pendingLabel="Запускаю…"
          plan={(b) => planAddGif(channel, b)}
          act={(confirm) => startAddGif(channel, confirm)}
          view={(p) => <AddPlanView plan={p} yes="можно нарезать" no="нарезать нельзя" ids={ids} />}
          problemText={memeJobProblemText}
          problemSay={say(ids)}
          onSettled={onSettled}
          onDone={onStarted}
        />
      </div>
    </div>
  );
}

function SheetForm({ channel, bankLabel, ids, busy, onStarted, onSettled }: FormProps) {
  const [f, setF] = useState({ video: '', start: '', end: '', every: '2', out: '' });
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  const start = seconds(f.start) ?? 0;
  const end = seconds(f.end);
  const every = seconds(f.every);
  const startBad = !!f.start.trim() && seconds(f.start) === null;
  const endBad = (!!f.end.trim() && end === null) || (end !== null && end <= start);
  const everyBad = !f.every.trim() || every === null || every <= 0;
  const outBad = /[/\\]|\.\./.test(f.out) || (!!f.out.trim() && !/\.(jpe?g|png)$/i.test(f.out));
  const frames = every && every > 0 ? sheetFrames(start, end, every) : null;
  const many = frames !== null && frames > MAX_SHEET_FRAMES;
  const why = first(
    !f.video.trim() && 'Вставьте ссылку на видео',
    urlBad(f.video) && `Ссылка на видео: ${URL_HINT.toLowerCase()}`,
    (startBad || start < 0) && 'Начало отрезка — секунды, не меньше 0',
    endBad && 'Конец отрезка должен быть позже начала',
    everyBad && 'Шаг между кадрами — больше 0 секунд',
    many && `В листе вышло бы ${frames} кадров, а можно не больше ${MAX_SHEET_FRAMES}`,
    outBad && 'Имя листа — одно имя файла .jpg или .png, без папок',
  );
  const body: SheetBody | null = why
    ? null
    : {
        video: f.video.trim(),
        start: f.start.trim() ? start : null,
        end,
        every,
        out: f.out.trim() || null,
      };
  return (
    <div className="grid gap-3" data-testid="meme-add-sheet">
      <p className="m-0 text-muted-foreground">
        Фабрика возьмёт видео по ссылке и склеит его кадры в одну картинку с метками времени и
        сменами сцен{NB}— по ней выбирают отрезок для гифки. В банк ничего не добавляется.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Ссылка на видео"
          tip="Страница видео (YouTube и т.п.) или прямая ссылка на файл"
          hint={URL_HINT}
          bad={urlBad(f.video)}
          className="sm:col-span-2"
        >
          {(id, d) => (
            <Text
              id={id}
              describedBy={d}
              value={f.video}
              onChange={(v) => set('video', v)}
              testId="sheet-video"
              placeholder="https://www.youtube.com/watch?v=…"
              url
              bad={urlBad(f.video)}
            />
          )}
        </Field>
        <div className="grid grid-cols-3 gap-3 sm:col-span-2 sm:max-w-md">
          <Field label="С, с" tip="Начало отрезка; пусто — с начала видео">
            {(id, d) => (
              <Text
                id={id}
                describedBy={d}
                value={f.start}
                onChange={(v) => set('start', v)}
                testId="sheet-start"
                placeholder="0"
                num
                bad={startBad}
              />
            )}
          </Field>
          <Field label="По, с" tip="Конец отрезка; пусто — до конца видео">
            {(id, d) => (
              <Text
                id={id}
                describedBy={d}
                value={f.end}
                onChange={(v) => set('end', v)}
                testId="sheet-end"
                placeholder="конец"
                num
                bad={endBad}
              />
            )}
          </Field>
          <Field label="Шаг, с" tip="Кадр каждые столько секунд">
            {(id, d) => (
              <Text
                id={id}
                describedBy={d}
                value={f.every}
                onChange={(v) => set('every', v)}
                testId="sheet-every"
                placeholder="2"
                num
                bad={everyBad}
              />
            )}
          </Field>
        </div>
        <p
          className={cn(
            'm-0 text-xs sm:col-span-2',
            many ? 'text-danger' : 'text-muted-foreground',
          )}
          data-testid="sheet-frames"
        >
          {frames === null
            ? `Без конца отрезка число кадров станет известно после извлечения; больше ${MAX_SHEET_FRAMES}${NB}— отказ.`
            : `В листе будет ${frames} кадров (не больше ${MAX_SHEET_FRAMES}).`}
        </p>
        <Field
          label="Имя листа"
          tip="Файл в папке листов кадров банка; пусто — sheet.jpg (тот же лист перезапишется)"
          hint="Одно имя файла .jpg или .png, без папок"
          bad={outBad}
        >
          {(id, d) => (
            <Text
              id={id}
              describedBy={d}
              value={f.out}
              onChange={(v) => set('out', v)}
              testId="sheet-out"
              placeholder="sheet.jpg"
              bad={outBad}
            />
          )}
        </Field>
      </div>
      <div>
        <WriteAction<SheetBody, MemeSheetPlan, MemeJobStarted>
          id="meme-sheet"
          label="Сделать лист кадров…"
          title={`Сделать лист кадров в банке ${bankLabel}?`}
          description={`Фабрика проверила без скачивания, что сделает. Лист соберётся в фоне${NB}— его ход виден на столе.`}
          body={body}
          why={busy ?? why}
          tip="Фабрика покажет план; видео скачается после вашего «да»"
          confirmLabel="Сделать лист"
          pendingLabel="Запускаю…"
          plan={(b) => planSheet(channel, b)}
          act={(confirm) => startSheet(channel, confirm)}
          view={(p) => <AddPlanView plan={p} yes="можно сделать" no="сделать нельзя" ids={ids} />}
          problemText={memeJobProblemText}
          problemSay={say(ids)}
          onSettled={onSettled}
          onDone={onStarted}
        />
      </div>
    </div>
  );
}

/** Панель «Добавить мем»: картинка, GIF из видео, лист кадров (раскрывает `AddToggle`). */
export function AddPanel({
  tab,
  onTab,
  seed,
  ...form
}: FormProps & { tab: AddTab; onTab: (t: AddTab) => void; seed: GifSeed | null }) {
  const ref = useRef<HTMLDivElement>(null);
  // Отрезок пришёл с листа кадров — форма GIF в поле зрения.
  useEffect(() => {
    if (seed) ref.current?.scrollIntoView?.({ block: 'nearest' });
  }, [seed]);
  return (
    <div
      ref={ref}
      id={ADD_PANEL}
      data-testid="meme-add-form"
      className="grid gap-3 rounded-sm border p-3 text-[13px] text-foreground"
    >
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Что добавить">
        {TABS.map((t) => (
          <Tip key={t.id} content={t.tip}>
            <Button
              size="sm"
              variant={tab === t.id ? 'default' : 'ghost'}
              aria-pressed={tab === t.id}
              data-testid={`add-tab-${t.id}`}
              onClick={() => onTab(t.id)}
            >
              {t.label}
            </Button>
          </Tip>
        ))}
      </div>
      {/* Все три формы живут, пока панель открыта: набранное не пропадает при смене вкладки. */}
      <div hidden={tab !== 'image'}>
        <ImageForm {...form} />
      </div>
      <div hidden={tab !== 'gif'}>
        <GifForm key={seed?.n ?? 0} {...form} seed={seed} onSheet={() => onTab('sheet')} />
      </div>
      <div hidden={tab !== 'sheet'}>
        <SheetForm {...form} />
      </div>
    </div>
  );
}

// ---- итоги задач

/** Признаки для поиска похожих после добавления — словами фабрики. */
export function EmbeddingLine({ e, testId }: { e: EmbeddingOutcome; testId: string }) {
  if (!e) return null;
  const text = e.error
    ? hasCyrillic(e.error)
      ? e.error
      : `Признаки для поиска похожих мемов не пересчитались: ${NO_REASON_TEXT}`
    : e.done
      ? 'Признаки для поиска похожих мемов пересчитаны.'
      : null;
  if (!text) return null;
  return (
    <span
      data-testid={testId}
      className={e.error ? (e.fatal ? 'text-danger' : 'text-warning') : undefined}
    >
      {nbDashes(text)}
    </span>
  );
}

/** Новая запись банка после «добавить картинку» или «GIF из видео»: ждёт разбора. */
export function AddDone({ job, onOpen }: { job: MemeJob; onOpen?: (id: string) => void }) {
  const r = addResult(job.result);
  const e = r.entry;
  const gif = job.kind === 'add_gif';
  const trimRu = r.trimNoteRu && hasCyrillic(r.trimNoteRu) ? r.trimNoteRu : null;
  return (
    <div className="grid gap-2" data-testid="add-done">
      {e ? (
        <div className="flex min-w-0 gap-3" data-testid="add-done-entry" data-id={e.id}>
          {e.urls?.thumb ? (
            <img
              src={e.urls.thumb}
              alt={`Новый мем: ${memeName(e.id)}`}
              loading="lazy"
              className="size-20 shrink-0 rounded-sm border bg-muted object-cover"
            />
          ) : null}
          <div className="grid min-w-0 content-start gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <b className="font-semibold">
                {gif ? 'Гифка' : 'Картинка'} «{memeName(e.id)}» в банке
              </b>
              <StatusBadge tone="live" tip="Новый мем ждёт решения: отметьте его на столе">
                ждёт разбора
              </StatusBadge>
            </div>
            {e.description ? (
              <span className="line-clamp-2 text-muted-foreground">{e.description}</span>
            ) : null}
            <span className="text-xs text-muted-foreground">
              {[
                r.size ? `${r.size[0]}×${r.size[1]}` : null,
                gif && r.durationS !== null ? `${sec(r.durationS)} с` : null,
                e.tags?.length ? `теги: ${e.tags.join(', ')}` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
            {onOpen ? (
              <div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onOpen(e.id)}
                  data-testid="add-done-open"
                >
                  Открыть на столе
                </Button>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <span>Готово.</span>
      )}
      {gif && r.cutsInside.length ? (
        <span className="text-warning" data-testid="add-done-cuts">
          Внутри отрезка смена сцены на {r.cutsInside.map(sec).join(', ')} с{NB}— на ней гифка
          прыгнет. Если это не нужно, сузьте отрезок по листу кадров и нарежьте заново.
        </span>
      ) : null}
      {trimRu ? <span data-testid="add-done-trim">{nbDashes(trimRu)}</span> : null}
      <EmbeddingLine e={r.embedding} testId="add-done-embedding" />
      <More className="mt-0">
        {e ? <span>id: {e.id}</span> : null}
        {r.file ? <span>файл: {r.file}</span> : null}
        {e?.source_url ? <span>источник: {e.source_url}</span> : null}
        {r.trimNote ? <span>{r.trimNote}</span> : null}
        {r.trimNoteRu && !trimRu ? <span>{r.trimNoteRu}</span> : null}
        {r.embedding?.line ? <span>{r.embedding.line}</span> : null}
        {r.embedding?.en ? <span>{r.embedding.en}</span> : null}
      </More>
    </div>
  );
}

/** Признаки для поиска похожих пересчитаны (задача «признаки»). */
export function EmbedDone({ job }: { job: MemeJob }) {
  const e = addResult(job.result).embedding;
  return (
    <div className="grid gap-1" data-testid="embed-done">
      <EmbeddingLine e={e ?? { done: true }} testId="embed-done-line" />
      {e?.line || e?.en ? (
        <More className="mt-0">
          {e.line ? <span>{e.line}</span> : null}
          {e.en ? <span>{e.en}</span> : null}
        </More>
      ) : null}
    </div>
  );
}

// ---- лист кадров

/** Время кадра `i` листа: как подпись фабрики (`t0 + i·шаг`). */
const frameAt = (start: number, every: number, i: number) =>
  Math.round((start + i * every) * 100) / 100;

/**
 * Лист кадров картинкой: метки смен сцен на кадрах, два щелчка — первый и последний кадр гифки
 * (или секунды руками), «Сделать GIF из отрезка» переносит отрезок в форму GIF.
 */
export function SheetDone({
  job,
  onGif,
}: {
  job: MemeJob;
  onGif?: (s: Omit<GifSeed, 'n'>) => void;
}) {
  const r = sheetResult(job.result);
  const p = sheetParams(job.params);
  const n = sheetFrames(p.start, p.end, p.every);
  const rows = n ? Math.ceil(n / SHEET_COLS) : null;
  const [pick, setPick] = useState<{ start: string; end: string }>({ start: '', end: '' });
  const start = seconds(pick.start);
  const end = seconds(pick.end);
  const last = p.end ?? Infinity;
  const choose = (t: number) => {
    // Первый щелчок — начало, второй — последний кадр (конец — после его шага); третий — заново.
    if (start === null || end !== null) return setPick({ start: sec(t), end: '' });
    const a = Math.min(start, t);
    const b = Math.min(Math.max(start, t) + p.every, last);
    setPick({ start: sec(a), end: sec(b) });
  };
  const inside =
    start !== null && end !== null ? r.sceneCuts.filter((c) => c > start && c < end) : [];
  const ok = start !== null && end !== null && start >= 0 && end > start;
  /** Кадр, с которого начинается новая сцена (смена — между ним и предыдущим). */
  const cutCells = new Map<number, number>();
  if (n)
    for (const c of r.sceneCuts) {
      const k = Math.floor((c - p.start) / p.every + 1e-9) + 1;
      if (k > 0 && k < n) cutCells.set(k, c);
    }
  const sel = (t: number) => start !== null && (end === null ? t === start : t >= start && t < end);
  return (
    <div className="grid gap-2" data-testid="sheet-done">
      {r.sheetUrl ? (
        <div className="grid gap-1">
          <div className="relative w-full overflow-hidden rounded-sm border bg-black">
            <img
              src={r.sheetUrl}
              alt="Лист кадров видео с метками времени"
              className="block h-auto w-full"
              data-testid="sheet-image"
            />
            {n && rows ? (
              <div className="absolute inset-0" data-testid="sheet-frames-grid">
                {Array.from({ length: n }, (_, i) => {
                  const t = frameAt(p.start, p.every, i);
                  const cut = cutCells.get(i);
                  return (
                    <button
                      key={i}
                      type="button"
                      aria-label={`Кадр ${sec(t)} с${cut !== undefined ? `, после смены сцены на ${sec(cut)} с` : ''}`}
                      aria-pressed={sel(t)}
                      data-testid="sheet-frame"
                      data-t={t}
                      title={`${sec(t)} с`}
                      onClick={() => choose(t)}
                      style={{
                        left: `${(i % SHEET_COLS) * (100 / SHEET_COLS)}%`,
                        top: `${Math.floor(i / SHEET_COLS) * (100 / rows)}%`,
                        width: `${100 / SHEET_COLS}%`,
                        height: `${100 / rows}%`,
                      }}
                      className={cn(
                        'absolute outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
                        sel(t) && 'bg-primary/35 ring-2 ring-primary ring-inset',
                      )}
                    >
                      {cut !== undefined ? (
                        <span
                          aria-hidden
                          data-testid="sheet-cut"
                          className="absolute inset-y-0 left-0 w-[3px] bg-danger"
                        />
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
          <a
            href={r.sheetUrl}
            target="_blank"
            rel="noreferrer"
            className="w-max text-xs text-primary-text underline underline-offset-2"
            data-testid="sheet-open"
          >
            Открыть лист целиком
          </a>
        </div>
      ) : (
        <span>Лист готов, но фабрика не сказала, где он.</span>
      )}
      <span data-testid="sheet-cuts">
        {r.sceneCuts.length ? (
          <>
            <span className="mr-1 inline-block h-3 w-[3px] bg-danger align-middle" aria-hidden />
            Смены сцен: {r.sceneCuts.map((c) => `${sec(c)} с`).join(' · ')}
          </>
        ) : (
          'Смен сцен в этом отрезке фабрика не нашла.'
        )}
      </span>
      {onGif && p.video ? (
        <div className="grid gap-2 rounded-sm border p-2.5" data-testid="sheet-pick">
          <span className="text-muted-foreground">
            {n
              ? 'Щёлкните первый и последний кадр гифки или впишите секунды.'
              : 'Время кадра подписано на листе: впишите начало и конец гифки в секундах.'}
          </span>
          <div className="flex flex-wrap items-end gap-2">
            <PickField
              label="Начало, с"
              value={pick.start}
              onChange={(v) => setPick((x) => ({ ...x, start: v }))}
              testId="sheet-pick-start"
            />
            <PickField
              label="Конец, с"
              value={pick.end}
              onChange={(v) => setPick((x) => ({ ...x, end: v }))}
              testId="sheet-pick-end"
            />
            <Button
              size="sm"
              disabled={!ok}
              onClick={() => ok && onGif({ video: p.video!, start: start!, end: end! })}
              data-testid="sheet-to-gif"
            >
              Сделать GIF из отрезка
            </Button>
          </div>
          {inside.length ? (
            <span className="text-warning" data-testid="sheet-pick-cuts">
              Внутри отрезка смена сцены на {inside.map(sec).join(', ')} с{NB}— на ней гифка
              прыгнет.
            </span>
          ) : null}
        </div>
      ) : null}
      <More className="mt-0">
        {r.sheet ? <span>лист: {r.sheet}</span> : null}
        {p.video ? <span>видео: {p.video}</span> : null}
        <span>
          кадр каждые {sec(p.every)} с от {sec(p.start)} с до{' '}
          {p.end === null ? 'конца' : `${sec(p.end)} с`}
          {n ? ` · ${n} кадров` : ''}
        </span>
        <span>смены сцен, с: {JSON.stringify(r.sceneCuts)}</span>
      </More>
    </div>
  );
}

function PickField({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testId: string;
}) {
  const id = useId();
  return (
    <div className="grid w-24 gap-1">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      <input
        id={id}
        value={value}
        inputMode="decimal"
        autoComplete="off"
        data-testid={testId}
        onChange={(e) => onChange(e.target.value)}
        className={inputBase}
      />
    </div>
  );
}
