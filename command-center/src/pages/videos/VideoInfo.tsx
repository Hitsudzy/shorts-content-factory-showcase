// Рядом с плеером: что журнал приёмки знает о ролике и кнопки вердикта (CC-0062, ./Acceptance)
// и разобранная карточка публикации (`…/card`): название, блоки описания, теги,
// слот, разделы, замечания; текст карточки целиком и пути — под «подробнее».
import type { ReactNode } from 'react';

import {
  useVideoCard,
  videoTitle,
  type ReasonCode,
  type Replacement,
  type Video,
  type VideoCard,
  type VideoRefusal,
} from '@/api/videos';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { dateTimeMsk } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { Refusal } from '@/pages/batches/parts';

import { useCardInfo } from '@/api/cards';
import { useQueue } from '@/api/publish';
import { useStash } from '@/api/stash';
import { CardActions, CardStateBadge } from '@/pages/publishing/CardState';
import { reasonsText } from '@/pages/publishing/cardWords';

import { AcceptanceActions } from './Acceptance';
import { acceptanceView, REPLACED_VIEW } from './format';
import { refusalLine } from './refusal';
import { SkeletonText } from '@/components/common/Skeletons';

/** Слова вердикта с названием ролика вместо его имени-латиницы (имя фабрика требует в словах). */
function wordsWithTitle(words: string, video: Video): string {
  const title = videoTitle(video);
  return title && title !== video.slug ? words.split(video.slug).join(title) : words;
}

function Field({
  label,
  children,
  testId,
}: {
  label: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div data-testid={testId} className="grid gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/**
 * Вердикт ролика как его видит журнал (и очередь под батчем) и кнопки «Да / Переделать / Нет»
 * (`batch` — батч, где ролик собран: у пересборки — её; `reasonCodes` — словарь причин батча).
 * Ролик заменён принятой пересборкой (`replacement`, CC-0088) — вердикт не предлагается: кнопки
 * спрятаны под «Всё равно дать вердикт этой версии» с предупреждением. Заменён ролик, отказанный
 * после монтажа (`refusal`, CC-0116), — вердикта нет совсем (фабрика ответит 409
 * `video_refused`), отказ — строкой ниже.
 */
export function AcceptanceState({
  batch,
  video,
  reasonCodes,
  recordError,
  replacement,
  refusal = null,
}: {
  batch: string;
  video: Video;
  reasonCodes: ReasonCode[];
  recordError?: string | null;
  replacement?: Replacement | null;
  refusal?: VideoRefusal | null;
}) {
  const a = video.acceptance;
  const view = replacement ? REPLACED_VIEW : acceptanceView(a);
  const actions = (
    <AcceptanceActions
      key={`${batch}|${video.slug}`}
      batch={batch}
      video={video}
      reasonCodes={reasonCodes}
    />
  );
  return (
    <Card
      aria-labelledby="acceptance-title"
      data-testid="acceptance"
      className="grid content-start gap-3"
    >
      <CardHead
        eyebrow="Приёмка"
        title="Ваше решение"
        titleId="acceptance-title"
        actions={
          <span data-testid="acceptance-verdict">
            <StatusBadge tone={view.tone} tip={view.tip}>
              {view.label}
            </StatusBadge>
          </span>
        }
      />
      {view.pending ? (
        <p
          data-testid="acceptance-pending"
          className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))] p-2.5 text-[13px]"
        >
          Записано, ждёт конца батча
          {a?.queued_at ? ` — в очереди с ${dateTimeMsk(a.queued_at)}` : ''}. Фабрика закоммитит
          вердикт, когда батч закончится.
          {a?.queued_verdicts && a.queued_verdicts > 1
            ? ` Вердиктов в очереди: ${a.queued_verdicts}, действует последний.`
            : ''}
        </p>
      ) : null}
      {a && view.decided ? (
        <dl className="m-0 grid gap-2 text-[13px]">
          {a.answer ? (
            <Field label="Ваши слова" testId="acceptance-words">
              «{wordsWithTitle(a.answer, video)}»
            </Field>
          ) : null}
          {a.reason ? (
            <Field label="Причина" testId="acceptance-reason">
              {a.reason}
            </Field>
          ) : null}
          {a.amended_because ? <Field label="Почему передумали">{a.amended_because}</Field> : null}
          {a.recorded_at || a.answered_at ? (
            <Field label="Когда">{dateTimeMsk(a.recorded_at) ?? a.answered_at}</Field>
          ) : null}
        </dl>
      ) : replacement && (refusal || (a && !a.state_error)) ? (
        <p className="m-0 text-muted-foreground" data-testid="acceptance-replaced">
          Вердикт не нужен: эту версию заменила пересборка, её вы приняли.
        </p>
      ) : a && !a.state_error ? (
        <p className="m-0 text-muted-foreground">Вердикта нет — ролик ждёт вашего решения.</p>
      ) : (
        <p className="m-0 text-danger">Журнал приёмки не читается — вердикт не показать.</p>
      )}
      {refusal ? (
        <p className="m-0 text-xs text-muted-foreground" data-testid="acceptance-was-refused">
          Эта версия не прошла проверку после монтажа: {refusalLine(refusal)}.
        </p>
      ) : replacement ? (
        <details data-testid="verdict-anyway" className="text-[13px]">
          <summary className="w-max cursor-pointer text-primary-text">
            Всё равно дать вердикт этой версии
          </summary>
          <div className="mt-2 grid gap-2.5">
            <p
              role="note"
              data-testid="verdict-anyway-warning"
              className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))] p-2.5"
            >
              Это первая версия, её уже заменила принятая пересборка. Вердикт ляжет в журнал
              отдельной строкой — только для этой версии: пересборку, её загрузку, слот и ротацию он
              не тронет. Обычно он не нужен.
            </p>
            {actions}
          </div>
        </details>
      ) : (
        actions
      )}
      <More>
        {a ? <span>запись: {a.entry_id}</span> : null}
        {a?.reason_code ? <span>код причины: {a.reason_code}</span> : null}
        {a?.note ? <span>пометка: {a.note}</span> : null}
        {a?.queued_by ? <span>в очередь поставил: {a.queued_by}</span> : null}
        {a?.hold_id ? <span>холд: {a.hold_id}</span> : null}
        {a?.state_error ? <span>{a.state_error}</span> : null}
        {recordError ? <span>{recordError}</span> : null}
        <span>вердикт — POST {video.accept_url}</span>
      </More>
    </Card>
  );
}

/**
 * Где ролик в публикации (CC-0128): «Публикация <дата>» — только у загруженного или стоящего в
 * слоте ленты; ролик копилки — «в копилке — слота пока нет»; остальные (не разложен, не решён)
 * — без строки: дата в карточке батча старая и путает.
 */
export type Placement =
  | { kind: 'uploaded' | 'placed'; at: string | null }
  | { kind: 'stash' }
  | { kind: 'reserve' }
  | { kind: 'none' };

function usePlacement(channel: string | null, video: Video, batchId: string | null): Placement {
  const uploaded = !!video.upload;
  const queue = useQueue(uploaded ? null : channel);
  const stash = useStash(uploaded ? null : channel);
  // CC-0180: снят из ленты — у строки журнала нет дня публикации, ролик лежит в запасе копилки.
  if (video.upload?.withdrawn) return { kind: 'reserve' };
  if (video.upload) return { kind: 'uploaded', at: video.upload.publish_at ?? null };
  const o = queue.data?.occupants.find((x) => x.slug === video.slug);
  if (o) return { kind: 'placed', at: o.at ?? null };
  // CC-0183: в копилке может лежать тёзка из другого батча — это не этот ролик.
  const inStash = stash.data?.videos.some(
    (x) => x.slug === video.slug && (!batchId || !x.batch_id || x.batch_id === batchId),
  );
  if (inStash) return { kind: 'stash' };
  return { kind: 'none' };
}

function publishText(card: VideoCard, where: Placement): string | null {
  if (where.kind === 'stash') return 'в копилке — слота пока нет';
  if (where.kind === 'reserve') return 'снят из ленты — лежит в запасе копилки';
  if (where.kind === 'none') return null;
  // Загруженный — дата из журнала загрузок; стоящий в слоте — из карточки дня (иначе — слот).
  const at =
    where.kind === 'uploaded' ? (where.at ?? card.publish_at) : (card.publish_at ?? where.at);
  return (at ? dateTimeMsk(at) : null) ?? card.publish_section ?? 'слот не назначен';
}

function CardBody({ card, where }: { card: VideoCard; where: Placement }) {
  const publish = publishText(card, where);
  const extra = card.sections.filter(
    (s) => !['Название', 'Описание', 'Теги', 'Публикация'].includes(s.name),
  );
  return (
    <>
      <h3 data-testid="card-title" className="m-0 text-[15px] font-semibold text-balance">
        {card.title || 'Без названия'}
      </h3>
      {card.description_blocks.length ? (
        <div data-testid="card-description" className="grid gap-2 text-[13px]">
          {card.description_blocks.map((b, i) => (
            <p key={i} className="m-0 whitespace-pre-line [overflow-wrap:anywhere]">
              {b}
            </p>
          ))}
        </div>
      ) : null}
      {card.tags?.length ? (
        <ul data-testid="card-tags" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {card.tags.map((t) => (
            <li key={t} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
              {t}
            </li>
          ))}
        </ul>
      ) : card.tags_raw ? (
        <p className="m-0 text-xs text-muted-foreground">Теги: {card.tags_raw}</p>
      ) : null}
      <dl className="m-0 grid gap-2 text-[13px]">
        {publish ? (
          <Field label="Публикация" testId="card-publish">
            <span data-where={where.kind}>{publish}</span>
          </Field>
        ) : null}
        {card.contains_synthetic ? (
          <Field label="Синтетика">в ролике есть синтетические кадры</Field>
        ) : null}
      </dl>
      {card.note_error ? (
        <p className="m-0 text-[13px] text-warning" data-testid="card-note-error">
          Раздел публикации не разобран: {card.note_error}
        </p>
      ) : null}
      {card.problems.length ? (
        <ul
          data-testid="card-problems"
          className="m-0 grid list-none gap-1 p-0 text-[13px] text-warning"
        >
          {card.problems.map((p, i) => (
            <li key={i}>⚠ {p}</li>
          ))}
        </ul>
      ) : null}
      {extra.length ? (
        <div className="grid gap-1.5" data-testid="card-sections">
          {extra.map((s, i) => (
            <details key={`${s.name}-${i}`} className="rounded-sm border px-2.5 py-1.5 text-[13px]">
              <summary className="cursor-pointer font-medium">{s.name}</summary>
              <p className="m-0 mt-1 whitespace-pre-line text-muted-foreground [overflow-wrap:anywhere]">
                {s.text}
              </p>
            </details>
          ))}
        </div>
      ) : null}
      <More>
        <span>файл: {card.path}</span>
        {card.status ? <span>метка: {card.status}</span> : null}
        <pre
          data-testid="card-raw"
          className="m-0 mt-1 max-h-80 overflow-auto rounded-sm border bg-background p-2.5 text-[11.5px] leading-[1.45] break-all whitespace-pre-wrap"
        >
          {card.raw}
        </pre>
      </More>
    </>
  );
}

/** Карточка публикации ролика (`batch` — батч, где ролик собран: у пересборки — её). */
export function PublishCard({
  batch,
  video,
  channel,
}: {
  batch: string;
  video: Video;
  /** Канал ролика (у пересборки — канал источника): сведения о карточке — `…/publish/{c}/cards`. */
  channel: string | null;
}) {
  const has = video.card.exists;
  const card = useVideoCard(batch, video.slug, has);
  const name = useChannelNames();
  // CC-0127: состояние карточки — из сведений фабрики (с опросом, пока собирается), иначе — из
  // списка роликов. Действия — когда фабрика знает карточку ролика (сведения прочитались).
  const batchId = batch.split('/')[1] ?? null;
  // Сведения — у принятого ролика и у карточки, с которой есть что делать (не готова, собирается,
  // принята решением); у прочих фабрика карточку центра не ведёт — незачем ловить 404.
  const known = video.card.card?.state;
  const info = useCardInfo(
    channel,
    video.slug,
    batchId,
    video.acceptance?.accepted === true ||
      known === 'not_ready' ||
      known === 'building' ||
      known === 'ruled',
  );
  const state = info.data ?? video.card.card ?? null;
  const where = usePlacement(channel, video, batchId);
  return (
    <Card
      aria-labelledby="card-title-head"
      data-testid="publish-card"
      className="grid content-start gap-3"
    >
      <CardHead
        eyebrow="Карточка публикации"
        title={channel ? `Что уйдёт в Studio · ${name(channel)}` : 'Что уйдёт в Studio'}
        titleId="card-title-head"
        actions={
          has || state ? (
            <CardStateBadge card={state ?? (has ? undefined : null)} channel={channel} />
          ) : null
        }
      />
      {state?.state === 'not_ready' && reasonsText(state) ? (
        <p className="m-0 text-[13px] text-warning" data-testid="card-state-why">
          Не готова: {reasonsText(state)}.
        </p>
      ) : state?.state === 'ruled' && state.ruling?.words ? (
        <p className="m-0 text-[13px]" data-testid="card-ruling-said">
          Принята вашим решением: «{state.ruling.words}»
        </p>
      ) : null}
      {!has ? (
        <div data-testid="card-none" className="grid gap-0">
          <p className="m-0 text-muted-foreground">
            Карточки публикации у ролика пока нет: публикатор её ещё не собрал.
          </p>
          {video.card.why ? (
            <More>
              <span>{video.card.why}</span>
            </More>
          ) : null}
        </div>
      ) : card.isPending ? (
        <SkeletonText lines={5} label="Читаю карточку…" />
      ) : card.isError ? (
        <Refusal error={card.error} title="Карточка не читается" />
      ) : (
        <>
          {!card.data.ready && card.data.why ? (
            <p className="m-0 text-[13px] text-warning" data-testid="card-why">
              {card.data.why}
            </p>
          ) : null}
          <CardBody card={card.data} where={where} />
        </>
      )}
      {info.data && channel ? (
        <CardActions
          channel={channel}
          slug={video.slug}
          batchId={info.data.batch_id ?? batchId}
          card={info.data}
          title={videoTitle(video)}
        />
      ) : null}
    </Card>
  );
}
