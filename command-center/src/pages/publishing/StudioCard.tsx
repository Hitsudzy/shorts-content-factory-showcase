// Карточка для Studio: поля ролика ровно так, как их ждёт форма YouTube Studio
// (`studio_fields.prepare` — только чтение), у каждого — «скопировать». Ответы формы,
// о которых настройки канала молчат, — «спросить вас», без кнопки: фабрика их не угадывает.
// Карточка не готова — отказ фабрики словами и то, что есть в карточке (название, описание).
// Отметить «загружено через Studio» — ./UploadWrites (CC-0069).
import { useNote, type FormField, type PublishNote, type StudioFields } from '@/api/publish';
import { BatchError } from '@/api/batchProblem';
import { Card, CardHead, Keep } from '@/components/common/Card';
import { CopyButton } from '@/components/common/CopyButton';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';
import { useChannelNames } from '@/pages/batches/names';

import { CardStateBadge } from './CardState';
import { withoutBatchTail } from './stashWords';
import { SkeletonText } from '@/components/common/Skeletons';

type Field = { key: string; label: string; value: string; long?: boolean; tip?: string };

function Row({ f }: { f: Field }) {
  return (
    <li
      data-testid="studio-field"
      data-field={f.key}
      className="grid gap-1.5 border-t py-2.5 first:border-t-0 first:pt-0"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow">{f.label}</span>
        <CopyButton value={f.value} what={f.label} tip={f.tip} data-testid={`copy-${f.key}`} />
      </div>
      <div
        data-testid="studio-value"
        className={cn(
          'min-w-0 text-[13.5px] [overflow-wrap:anywhere] select-all',
          f.long && 'max-h-48 overflow-y-auto whitespace-pre-wrap',
        )}
      >
        {f.value}
      </div>
    </li>
  );
}

const formText = (f: FormField) =>
  f.studio ?? (typeof f.value === 'string' ? f.value : f.value == null ? null : String(f.value));

function fieldsOf(s: StudioFields): Field[] {
  const sched = s.schedule as Record<string, unknown>;
  const str = (k: string) => (typeof sched[k] === 'string' ? (sched[k] as string) : null);
  const out: Field[] = [
    {
      key: 'file',
      label: 'Файл ролика',
      value: s.file_name,
      tip: 'Имя файла, который перетащить в Studio',
    },
    { key: 'title', label: 'Название', value: s.title },
    { key: 'description', label: 'Описание', value: s.description, long: true },
    {
      key: 'tags',
      label: 'Теги',
      value: s.tags_input,
      tip: 'Теги через запятую — как их ждёт Studio',
    },
    {
      key: 'visibility',
      label: 'Видимость',
      value: s.visibility_studio,
      tip: 'Что выбрать на шаге «Доступ» в Studio',
    },
  ];
  const date = str('date_picker_text');
  const time = str('time');
  const zone = str('zone_label') ?? str('zone_offset');
  if (date) out.push({ key: 'date', label: 'Дата', value: date, tip: 'Как дату пишет Studio' });
  if (time) out.push({ key: 'time', label: 'Время', value: time });
  if (zone)
    out.push({
      key: 'zone',
      label: 'Часовой пояс',
      value: zone,
      tip: 'Выберите пояс явно: по умолчанию Studio берёт пояс компьютера',
    });
  return out;
}

function FormAnswers({ form }: { form: Record<string, FormField> }) {
  const entries = Object.entries(form);
  if (!entries.length) return null;
  return (
    <div className="mt-4 grid gap-2" data-testid="studio-form">
      <h3 className="eyebrow">Ответы формы Studio</h3>
      <ul className="m-0 grid list-none p-0">
        {entries.map(([key, f]) => {
          const text = formText(f);
          return f.ask_user || !text ? (
            <li
              key={key}
              data-testid="studio-ask"
              data-field={key}
              className="grid gap-1 border-t py-2.5 first:border-t-0 first:pt-0"
            >
              <span className="eyebrow">{f.label}</span>
              <span className="flex flex-wrap items-center gap-2 text-[13px]">
                <StatusBadge
                  tone="warn"
                  tip="Настройки канала об этом молчат — фабрика не угадывает ответ"
                >
                  спросить вас
                </StatusBadge>
                <span className="text-muted-foreground">Ответ выберите сами в Studio.</span>
              </span>
            </li>
          ) : (
            <Row key={key} f={{ key: `form-${key}`, label: f.label, value: text }} />
          );
        })}
      </ul>
    </div>
  );
}

function Fields({ note }: { note: PublishNote }) {
  const s = note.studio;
  if (!s)
    return (
      <>
        <div
          role="note"
          data-testid="studio-refusal"
          className="mb-3 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] p-3 text-[13px]"
        >
          <div className="font-semibold text-warning">Поля для Studio не готовы</div>
          <p className="m-0 mt-1 text-muted-foreground">
            Фабрика не собрала поля для этой карточки — причина под «подробнее». Ниже — то, что уже
            есть в карточке.
          </p>
        </div>
        <ul className="m-0 grid list-none p-0">
          <Row f={{ key: 'title', label: 'Название', value: note.title }} />
          <Row f={{ key: 'description', label: 'Описание', value: note.description, long: true }} />
        </ul>
        <FormAnswers form={note.form} />
      </>
    );
  return (
    <>
      {s.notices.length ? (
        <ul className="m-0 mb-3 grid list-none gap-1 p-0 text-[13px]" data-testid="studio-notices">
          {s.notices.map((n) => (
            <li key={n} className="text-warning">
              {n.startsWith('уже загружен')
                ? 'Ролик уже загружен в YouTube — поля здесь для сверки.'
                : n}
            </li>
          ))}
        </ul>
      ) : null}
      <ul className="m-0 grid list-none p-0">
        {fieldsOf(s).map((f) => (
          <Row key={f.key} f={f} />
        ))}
      </ul>
      <FormAnswers form={s.form} />
    </>
  );
}

/**
 * CC-0168 (API CC-0167): у имени два места и больше, а день не назван — 404 `unknown_note`,
 * строка фабрики просит день. Её и показываем как есть: что не так и где искать.
 */
function askedDay(e: unknown): string | null {
  const p = e instanceof BatchError ? e.problem : null;
  // Код отказа заметок (PublishProblem) шире BatchProblemCode: сверяем строкой.
  const code: string | undefined = p?.code;
  return p && code === 'unknown_note' && /укажите день/i.test(p.message) ? p.message : null;
}

/**
 * CC-0183: голое имя двух роликов. Повтор снова даст отказ, а оператор батчи не называет: он выбирает
 * строку копилки. Слова центра по коду (как `NAMESAKES_TEXT`), строка фабрики — под «Подробнее».
 */
function isNamesakes(e: unknown): boolean {
  // Код отказа заметок (PublishProblem) шире BatchProblemCode: сверяем строкой.
  const code: string | undefined = e instanceof BatchError ? e.problem?.code : undefined;
  return code === 'namesakes';
}

function NamesakesWords() {
  return (
    <span data-testid="studio-namesakes">
      Роликов с этим именем несколько. Откройте нужный{' '}
      <a
        href="#stash"
        data-testid="studio-namesakes-stash"
        className="text-primary-text underline-offset-4 hover:underline"
      >
        в копилке
      </a>
      : у каждого своя метка батча.
    </span>
  );
}

export function StudioCard({
  channel,
  slug,
  day,
  batchId = null,
}: {
  channel: string;
  slug: string | null;
  day: string | null;
  /** CC-0183: какой из тёзок копилки (`&batch=` адреса). */
  batchId?: string | null;
}) {
  const note = useNote(channel, slug, day, batchId);
  const name = useChannelNames();
  const head = (title: string) => (
    <CardHead
      eyebrow={
        <>
          <span>Для Studio</span> · <Keep data-testid="studio-channel">{name(channel)}</Keep>
        </>
      }
      title={title}
      titleId="studio-title"
    />
  );
  return (
    <Card
      aria-labelledby="studio-title"
      data-testid="studio-card"
      data-tour="studio"
      data-slug={slug ?? ''}
      data-batch={batchId ?? undefined}
    >
      {!slug ? (
        <>
          {head('Выберите ролик')}
          <EmptyState title="Ролик не выбран">
            Нажмите занятый слот в ленте — здесь появятся поля для YouTube Studio.
          </EmptyState>
        </>
      ) : note.isPending ? (
        <>
          {head('Читаю карточку…')}
          <SkeletonText lines={6} label="Читаю карточку ролика…" />
        </>
      ) : note.isError ? (
        <>
          {head('Карточка не читается')}
          <ErrorState
            title="Карточку ролика не прочитать"
            error={note.error}
            onRetry={isNamesakes(note.error) ? undefined : () => void note.refetch()}
          >
            {isNamesakes(note.error) ? (
              <NamesakesWords />
            ) : (
              (askedDay(note.error) ??
              (note.error instanceof BatchError && note.error.problem
                ? 'Фабрика не нашла карточку этого ролика в папке дня.'
                : 'Проверьте, что API фабрики запущен.'))
            )}
          </ErrorState>
        </>
      ) : (
        <>
          {head(note.data.title || 'Без названия')}
          <div className="mb-3 flex flex-wrap gap-1.5">
            {/* CC-0127: состояние карточки — готова, вашим решением, собирается, не готова. */}
            <CardStateBadge
              card={note.data.card ?? { state: note.data.ready ? 'ready' : 'not_ready' }}
              channel={channel}
              prefix="карточка"
              testId="studio-card-state"
            />
          </div>
          <Fields note={note.data} />
          <More>
            <span>карточка: {withoutBatchTail(note.data.path)}</span>
            {note.data.batch ? <span>батч: {note.data.batch.path}</span> : null}
            {note.data.studio ? <span>запись: {note.data.studio.entry_id}</span> : null}
            {note.data.studio ? (
              <span>файл: {withoutBatchTail(note.data.studio.video_file)}</span>
            ) : null}
            {note.data.why ? <span>не готова: {note.data.why}</span> : null}
            {note.data.studio_refusal ? <span>{note.data.studio_refusal}</span> : null}
            {note.data.studio?.notices.map((n) => (
              <span key={n}>{n}</span>
            ))}
            <span className="whitespace-pre-wrap">{withoutBatchTail(note.data.view)}</span>
          </More>
        </>
      )}
    </Card>
  );
}
