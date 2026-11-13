// Карточка ролика (CC-0068, API CC-0065): разместить готовую карточку батча рядом с роликом в
// publish/ — из очереди в ближайший свободный слот (`publish_queue.plan_slot`: слот, сдвиги
// соседних роликов, предупреждения; на паузе карточка остаётся в очереди) — и собрать карточку
// из своего черновика (название, описание, хэштеги, теги). Собранная здесь выходит «утверждения
// не проверены» (`claims_not_checked`) и в слот не идёт: черновик моделью и проверку
// утверждений делает сборка у оператора — центр модель не зовёт (`model_refused`). Ролик и батч
// берутся из выбранного в ленте слота или из очереди; пути и имена файлов — под «подробнее».
// CC-0168 (API CC-0167): «День» — папка, где ролик лежит сейчас, а не слот; пусто — фабрика сама
// найдёт ролик батча. У ролика из копилки («ждёт слота») поля нет: из `_queue/` он идёт в
// ближайший свободный слот, а слот под ролик выбирается в «Разложить по слотам».
import { useState } from 'react';

import type { PublishNote } from '@/api/publish';
import {
  batchOf,
  cardBuild,
  cardPlace,
  listOf,
  planCardBuild,
  planCardPlace,
  WRITE_PROBLEM_TEXT,
  type CardBuildPlan,
  type CardBuildResult,
  type CardPlacePlan,
  type CardPlaceResult,
  type PlannedSlot,
} from '@/api/publishWrites';
import { useStash } from '@/api/stash';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { dateTimeMsk } from '@/pages/batches/format';

import {
  inReserve,
  namesakeMark,
  namesakesOf,
  RESERVE_DAY,
  RESERVE_WHY,
  stashBatch,
  stashKeyOf,
  withMark,
  withoutBatchTail,
} from './stashWords';
import { Check, Disclosure, Done, Field, PlanHead, WriteAction } from './Writes';

const CLAIMS_TIP =
  'Утверждения карточки (цифры, даты, источники) не проверены: такую карточку фабрика в слот не ставит';

export function PlacePlan({ plan }: { plan: CardPlacePlan }) {
  const slot = plan.slot as PlannedSlot | null | undefined;
  return (
    <>
      <PlanHead plan={plan} yes="можно разместить" no="разместить нельзя" />
      {plan.ok ? (
        <p className="m-0" data-testid="place-where">
          {plan.paused
            ? 'Канал на паузе: карточка ляжет рядом с роликом в очереди, слот не займётся.'
            : slot?.slot
              ? `Ролик встанет в слот ${dateTimeMsk(slot.slot) ?? slot.slot}.`
              : slot?.beyond_horizon
                ? 'Ролик останется в копилке: ближайший свободный слот дальше горизонта ленты.'
                : 'Карточка ляжет рядом с роликом в папке его дня.'}
        </p>
      ) : null}
      {plan.target_exists && plan.ok ? (
        <p className="m-0 text-warning" data-testid="place-replace">
          Заметка рядом с роликом уже есть — она заменится.
        </p>
      ) : null}
      {slot?.moves.length ? (
        <div className="grid gap-1" data-testid="place-moves">
          <span className="font-medium">Сдвинутся другие ролики:</span>
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {slot.moves.map((m, i) => (
              <li key={i} data-testid="place-move">
                {m.from === '_queue' ? 'из очереди' : `с ${m.from}`} →{' '}
                {m.slot ? (dateTimeMsk(m.slot) ?? m.day) : m.day}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {slot?.warnings.length ? (
        <div className="grid gap-1" data-testid="place-warnings">
          <span className="font-medium">Фабрика предупреждает:</span>
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {slot.warnings.map((w) => (
              <li key={w} className="text-warning [overflow-wrap:anywhere]">
                {w}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {slot?.note && !slot.beyond_horizon ? (
        <p className="m-0 text-muted-foreground">{slot.note}</p>
      ) : null}
      <More className="mt-0">
        {slot?.note && slot.beyond_horizon ? <span>{slot.note}</span> : null}
        {plan.batch ? <span>батч: {plan.batch}</span> : null}
        {plan.slug ? <span>ролик: {plan.slug}</span> : null}
        {plan.card ? <span>карточка: {plan.card}</span> : null}
        {plan.target ? <span>куда: {plan.target}</span> : null}
        {slot?.line ? <span>{slot.line}</span> : null}
        {slot?.moves.map((m, i) => (
          <span key={i}>
            сдвиг: {m.slug} {m.from} → {m.day}
            {m.line ? ` (${m.line})` : ''}
          </span>
        ))}
        {plan.paused ? <span>{plan.paused}</span> : null}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function BuildPlan({ plan }: { plan: CardBuildPlan }) {
  return (
    <>
      <PlanHead plan={plan} yes="можно собрать" no="собрать нельзя" />
      {plan.ok ? (
        <>
          <p className="m-0" data-testid="build-what">
            {plan.exists
              ? 'Карточка в батче уже есть — она заменится собранной из вашего черновика.'
              : 'В батче появится карточка из вашего черновика.'}
          </p>
          <p className="m-0 flex flex-wrap items-center gap-2" data-testid="build-claims">
            <StatusBadge tone="warn" tip={CLAIMS_TIP}>
              утверждения не проверены
            </StatusBadge>
            <span className="text-muted-foreground">
              В слот такая карточка не пойдёт, пока её утверждения не проверит сборка у оператора.
            </span>
          </p>
        </>
      ) : null}
      <More className="mt-0">
        {plan.out ? <span>карточка: {plan.out}</span> : null}
        {(plan.problems ?? []).map((p) => (
          <span key={p}>{p}</span>
        ))}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function PlaceDone({ r, onClose }: { r: CardPlaceResult; onClose: () => void }) {
  const paused = r.report.some((l) => l.startsWith('PAUSED'));
  const warned = r.report.some((l) => l.startsWith('WARNING'));
  return (
    <Done
      tone={paused || warned ? 'warn' : 'ok'}
      title="Карточка размещена"
      testId="place-done"
      onClose={onClose}
    >
      <span>
        {paused
          ? 'Канал на паузе — карточка лежит рядом с роликом в очереди.'
          : 'Карточка лежит рядом с роликом; лента обновилась.'}
      </span>
      {warned ? (
        <span className="text-warning">Фабрика предупредила — под «подробнее».</span>
      ) : null}
      <More className="mt-0">
        <span>{withoutBatchTail(r.path)}</span>
        {r.report.map((l) => (
          <span key={l}>{l}</span>
        ))}
      </More>
    </Done>
  );
}

function BuildDone({ r, onClose }: { r: CardBuildResult; onClose: () => void }) {
  return (
    <Done
      tone="warn"
      title="Карточка собрана — утверждения не проверены"
      testId="build-done"
      onClose={onClose}
    >
      <span>В слот она не пойдёт, пока её утверждения не проверит сборка у оператора.</span>
      <More className="mt-0">
        <span>{withoutBatchTail(r.path)}</span>
        <span>состояние: {r.status}</span>
        <span>{JSON.stringify(r.mark)}</span>
        <span className="whitespace-pre-wrap">{r.view}</span>
      </More>
    </Done>
  );
}

/** Папка дня строки ленты (`YYYY-MM-DD`); у копилки (`_queue`) дня в поле нет. */
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

const DAY_LABEL = 'День: папка, где ролик лежит сейчас (не слот)';

export function CardWrites({
  channel,
  note,
  waiting,
}: {
  channel: string;
  /** Карточка выбранного в ленте слота (если она есть). */
  note: PublishNote | undefined;
  /** Ролики очереди канала (`_queue/`). */
  waiting: string[];
}) {
  const [batch, setBatch] = useState('');
  const [slug, setSlug] = useState('');
  const [day, setDay] = useState('');
  /** Ролик взят кнопкой «ждёт слота» — он в копилке, дня у него нет (CC-0168). */
  const [queued, setQueued] = useState(false);
  const [replace, setReplace] = useState(false);
  const [draft, setDraft] = useState({ title: '', about: '', hashtags: '', tags: '' });
  const [model, setModel] = useState(false);
  const [placed, setPlaced] = useState<CardPlaceResult | null>(null);
  const [built, setBuilt] = useState<CardBuildResult | null>(null);

  const b = batchOf(batch);
  const at = b && slug.trim() ? { ...b, slug: slug.trim() } : null;
  const whyAt = !slug.trim()
    ? 'Выберите ролик'
    : !b
      ? 'Укажите батч ролика: «каталог/батч» или только батч'
      : null;
  const d = {
    title: draft.title.trim(),
    about: draft.about.trim(),
    hashtags: listOf(draft.hashtags, true),
    tags: listOf(draft.tags),
  };
  const whyDraft =
    whyAt ??
    (!d.title || !d.about
      ? 'Напишите название и описание: центр собирает карточку только из вашего черновика'
      : null);
  // CC-0180: ролик запаса на слот через карточку не поставить: день ему возвращает копилка.
  const reservedNote = note?.day === RESERVE_DAY;
  const fromNote = !reservedNote && note?.batch && !note.batch.error ? note.batch : null;
  const videos = useStash(channel).data?.videos ?? [];
  const names = namesakesOf(videos);
  // `waiting` называет имя один раз: тёзки копилки разворачиваются в свои кнопки с батчем (CC-0183).
  const picks = waiting.flatMap((w) => {
    const same = videos.filter((v) => v.slug === w);
    const queued = same.filter((v) => !inReserve(v));
    if (same.length && !queued.length) return [];
    const named: { slug: string; batch_id?: string | null }[] = names.has(w)
      ? queued
      : [{ slug: w }];
    return named;
  });
  const typed = slug.trim();
  const sameName = videos.filter((v) => v.slug === typed);
  const typedReserved =
    sameName.some(inReserve) &&
    !sameName.some((v) => !inReserve(v) && (!b || v.batch_id === b.batch_id));
  const noteReserved =
    reservedNote &&
    typed === note.slug &&
    (!b || !note.batch?.batch_id || note.batch.batch_id === b.batch_id);
  const whyPlace = typedReserved || noteReserved ? RESERVE_WHY : whyAt;

  return (
    <Card aria-labelledby="card-writes-title" data-testid="card-writes">
      <CardHead
        eyebrow="Карточка ролика"
        title="Разместить или собрать"
        titleId="card-writes-title"
      />
      <div className="grid gap-3 text-[13px]">
        <div className="grid gap-2 sm:grid-cols-2">
          <Field
            label="Батч"
            value={batch}
            onChange={setBatch}
            testId="card-batch"
            placeholder="канал/2026-10-09T0200Z"
            tip="Из какого батча карточка: «каталог/батч» (каталог — канал или rebuilds)"
          />
          <Field
            label="Ролик"
            value={slug}
            onChange={(v) => {
              setSlug(v);
              setQueued(false);
            }}
            testId="card-slug"
            placeholder="имя ролика"
            tip="Имя ролика в батче (или его сценарий)"
          />
        </div>
        {reservedNote ? (
          <p className="m-0 text-xs text-muted-foreground" data-testid="card-pick-reserve">
            {RESERVE_WHY}
          </p>
        ) : null}
        {fromNote || picks.length ? (
          <div className="flex flex-wrap items-center gap-1.5" data-testid="card-pick">
            <span className="text-xs text-muted-foreground">Взять:</span>
            {fromNote ? (
              <Tip content="Ролик выбранного в ленте слота — с его батчем">
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="card-pick-selected"
                  onClick={() => {
                    setBatch(fromNote.path);
                    setSlug(fromNote.slug ?? note!.slug);
                    setQueued(false);
                    // CC-0168: ролик строки ленты лежит в папке её дня — её и передаём.
                    setDay(DAY_RE.test(note!.day) ? note!.day : '');
                  }}
                >
                  выбранный в ленте
                </Button>
              </Tip>
            ) : null}
            {picks.map((p, i) => {
              const mark = namesakeMark(names, p.slug, p.batch_id);
              const batchOfPick = mark ? videos.find((v) => stashKeyOf(v) === stashKeyOf(p)) : null;
              return (
                <Tip
                  key={stashKeyOf(p)}
                  content={
                    mark
                      ? 'Ролик ждёт слота в очереди; батч подставится сам'
                      : 'Ролик ждёт слота в очереди; батч укажите сами'
                  }
                >
                  <Button
                    size="sm"
                    variant="ghost"
                    data-testid="card-pick-waiting"
                    data-slug={p.slug}
                    data-batch={mark ? (p.batch_id ?? undefined) : undefined}
                    onClick={() => {
                      setSlug(p.slug);
                      setQueued(true);
                      setDay('');
                      const dir = batchOfPick ? stashBatch(batchOfPick) : null;
                      if (dir) setBatch(dir);
                    }}
                  >
                    {withMark(picks.length > 1 ? `ждёт слота · ${i + 1}` : 'ждёт слота', mark)}
                  </Button>
                </Tip>
              );
            })}
          </div>
        ) : null}

        <div className="flex flex-wrap items-start gap-2">
          <Disclosure
            id="card-place"
            label="Разместить в слот"
            tip="Положить готовую карточку батча рядом с роликом; из очереди — в ближайший свободный слот"
          >
            {queued ? (
              <p className="m-0 text-xs text-muted-foreground" data-testid="card-day-queued">
                Ролик из копилки: день не нужен — из очереди он встанет в ближайший свободный слот.
                Слот под ролик выбирается в «Разложить по слотам».
              </p>
            ) : (
              <Field
                label={DAY_LABEL}
                type="date"
                value={day}
                onChange={setDay}
                testId="card-day"
                tip="Не слот публикации, а папка дня в publish/, где ролик батча лежит сейчас. Слот выбирается в «Разложить по слотам»"
                hint={
                  <span data-testid="card-day-hint">
                    Слот выбирается в «Разложить по слотам». Пусто — фабрика сама найдёт ролик этого
                    батча.
                  </span>
                }
              />
            )}
            <Check
              label="Заменить заметку, если она уже лежит"
              checked={replace}
              onChange={setReplace}
              testId="card-replace"
              tip="Без этого фабрика не трогает заметку, что уже лежит рядом с роликом"
            />
            <WriteAction
              id="card-place"
              label="Проверить и разместить…"
              title="Разместить карточку?"
              description="Фабрика проверила карточку, ролик и слот."
              body={at ? { ...at, day: (!queued && day) || null, replace } : null}
              why={whyPlace}
              tip="Фабрика проверит карточку и слот и покажет план; запись — после вашего «да»"
              confirmLabel="Разместить"
              plan={(x) => planCardPlace(channel, x)}
              act={(c) => cardPlace(channel, c)}
              view={(p) => <PlacePlan plan={p} />}
              onDone={setPlaced}
            />
          </Disclosure>
          <Disclosure
            id="card-build"
            label="Собрать из черновика"
            tip="Собрать карточку батча из вашего черновика — без модели и без проверки утверждений"
          >
            <Field
              label="Название"
              value={draft.title}
              onChange={(v) => setDraft((x) => ({ ...x, title: v }))}
              testId="draft-title"
            />
            <Field
              label="Описание"
              rows={3}
              value={draft.about}
              onChange={(v) => setDraft((x) => ({ ...x, about: v }))}
              testId="draft-about"
            />
            <Field
              label="Хэштеги"
              value={draft.hashtags}
              onChange={(v) => setDraft((x) => ({ ...x, hashtags: v }))}
              testId="draft-hashtags"
              placeholder="#Zenith #MCU"
              tip="Через пробел; решётку фабрика поставит сама"
            />
            <Field
              label="Теги"
              value={draft.tags}
              onChange={(v) => setDraft((x) => ({ ...x, tags: v }))}
              testId="draft-tags"
              placeholder="Zenith, release date"
              tip="Через запятую"
            />
            <p className="m-0 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <StatusBadge tone="warn" tip={CLAIMS_TIP}>
                утверждения не проверены
              </StatusBadge>
              Так выйдет собранная здесь карточка.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <WriteAction
                id="card-build"
                label="Проверить и собрать…"
                title="Собрать карточку из черновика?"
                description="Фабрика проверила черновик. Модель не зовётся, утверждения не проверяются."
                body={at && !whyDraft ? { ...at, draft: d } : null}
                why={whyDraft}
                tip="Фабрика проверит черновик и покажет план; запись — после вашего «да»"
                confirmLabel="Собрать"
                plan={(x) => planCardBuild(channel, x)}
                act={(c) => cardBuild(channel, c)}
                view={(p) => <BuildPlan plan={p} />}
                onDone={setBuilt}
              />
              <Button
                size="sm"
                variant="ghost"
                aria-expanded={model}
                data-testid="card-build-model"
                onClick={() => setModel((v) => !v)}
              >
                Черновик моделью?
              </Button>
            </div>
            {model ? (
              <div
                role="note"
                data-testid="model-refused"
                className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] p-3"
              >
                <b className="font-semibold text-warning">{WRITE_PROBLEM_TEXT.model_refused}</b>
                <span className="text-muted-foreground">
                  Центр собирает карточку только из вашего черновика и без проверки утверждений.
                  Черновик моделью и проверку утверждений делает сборка карточки у оператора.
                </span>
                <More className="mt-0">
                  <span>publish_card.py build (с моделью и проверкой утверждений)</span>
                </More>
              </div>
            ) : null}
          </Disclosure>
        </div>
        {placed ? <PlaceDone r={placed} onClose={() => setPlaced(null)} /> : null}
        {built ? <BuildDone r={built} onClose={() => setBuilt(null)} /> : null}
      </div>
    </Card>
  );
}
