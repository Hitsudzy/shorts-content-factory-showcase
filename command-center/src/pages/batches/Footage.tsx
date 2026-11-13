// «Футаж по темам» на карточке батча (CC-0119, фабрика CF-0715 `footage_progress`): как идёт
// сбор футажа каждой темы — состояние словами фабрики (`state_ru`), источников собрано из
// нужного, пригодных кадров против порога, последнее взятое видео, причина «не хватило» и
// «отказано» по-русски. Пока батч идёт — опрос раз в `poll_s`. У батчей, чья разметка футажа
// файла прогресса не пишет, ответ собран по журналу (`source: events`) — так и сказано в
// подсказке. Коды состояний и причин, файл и время — только под «Подробнее».
import { useBatchFootage, type FootageTopic } from '@/api/batches';
import type { BatchTopics } from '@/api/batchTopics';
import { codeWithWords, reasonWords } from '@/api/reasonRu';
import { More } from '@/components/common/More';
import { Pending, SkeletonRows } from '@/components/common/Skeletons';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';

import { countsLine, factsOf, SOURCE_TIP, SOURCE_WORD, stateTone, stateWord } from './footageText';
import { dateTimeMsk } from './format';
import { topicName, topicNames } from './words';

function TopicLine({ t, name }: { t: FootageTopic; name: string }) {
  const facts = factsOf(t);
  const why = t.state === 'short' || t.state === 'refused';
  return (
    <li
      data-testid="footage-topic"
      data-topic={t.topic_id}
      data-state={t.state}
      className="grid gap-1 border-t py-2 first:border-t-0"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <b className="min-w-0 font-semibold [overflow-wrap:anywhere]">{name}</b>
        <StatusBadge tone={stateTone(t.state)}>
          <span data-testid="footage-state">{stateWord(t)}</span>
        </StatusBadge>
      </div>
      {facts.length ? (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
          {facts.map((f) => (
            <span
              key={f.text}
              data-testid="footage-fact"
              className={cn('[overflow-wrap:anywhere]', f.low && 'text-warning')}
            >
              {f.text}
            </span>
          ))}
        </div>
      ) : null}
      {why ? (
        <span data-testid="footage-reason" className="[overflow-wrap:anywhere]">
          {t.state === 'short' ? 'Почему не хватило: ' : 'Почему отказано: '}
          {reasonWords(t) ?? 'фабрика причину не назвала'}
        </span>
      ) : null}
    </li>
  );
}

/** Блок «Футаж по темам»: `going` — батч идёт (опрос); `topics` — названия тем батча. */
export function FootageBlock({
  batch,
  going,
  topics,
}: {
  batch: string;
  going: boolean;
  topics?: BatchTopics;
}) {
  const q = useBatchFootage(batch, going);
  if (q.isPending) {
    if (!going) return null;
    return (
      <section data-testid="footage" className="mt-3 grid gap-2 rounded-sm border p-3">
        <h3 className="m-0 text-[13px] font-semibold">Футаж по темам</h3>
        <Pending label="Читаю сбор футажа…">
          <SkeletonRows bare rows={3} height={52} gap={6} />
        </Pending>
      </section>
    );
  }
  if (q.isError && !q.data) {
    if (!going) return null;
    return (
      <p className="mt-3 mb-0 text-[13px] text-muted-foreground" data-testid="footage-error">
        Сбор футажа по темам сейчас не читается — посмотрим при следующем опросе.
      </p>
    );
  }
  const f = q.data;
  if (!f || !f.topics.length) return null;
  const names = topicNames(topics);
  const tip = SOURCE_TIP[f.source];
  const updated = dateTimeMsk(f.updated_at);
  return (
    <section
      data-testid="footage"
      data-source={f.source}
      aria-label="Футаж по темам"
      className="mt-3 grid gap-2 rounded-sm border p-3 text-[13px]"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="m-0 text-[13px] font-semibold">
          Футаж по темам
          <span className="ml-2 font-normal text-muted-foreground" data-testid="footage-counts">
            {countsLine(f)}
          </span>
        </h3>
        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {tip ? (
            <Tip content={tip}>
              <span
                tabIndex={0}
                data-testid="footage-source"
                className="underline decoration-dotted underline-offset-4"
              >
                {SOURCE_WORD[f.source]}
              </span>
            </Tip>
          ) : null}
          {updated ? <span>обновлено {updated}</span> : null}
        </span>
      </div>
      {f.error ? (
        <p className="m-0 text-muted-foreground" data-testid="footage-file-error">
          Файл хода сбора не прочитался — показано по журналу.
        </p>
      ) : null}
      <ul className="m-0 grid list-none gap-0 p-0">
        {f.topics.map((t) => (
          <TopicLine key={t.topic_id} t={t} name={topicName(t.topic_id, names)} />
        ))}
      </ul>
      <More className="mt-0">
        <span>источник: {f.source}</span>
        {f.file ? <span>файл {f.file}</span> : null}
        {f.error ? <span>{f.error}</span> : null}
        {f.needed != null ? <span>тема идёт до {f.needed} источников</span> : null}
        {f.started_at ? <span>начат {f.started_at}</span> : null}
        {f.updated_at ? <span>обновлён {f.updated_at}</span> : null}
        <span>{f.cached ? 'ответ из кэша — файлы не менялись' : 'ответ свежий'}</span>
        {f.topics.map((t) => (
          <span key={`raw-${t.topic_id}`}>
            {[
              t.topic_id,
              t.state,
              codeWithWords(t),
              t.reason,
              t.attempts != null ? `кандидатов ${t.attempts}` : null,
              t.indexed_at ? `размечено ${t.indexed_at}` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        ))}
      </More>
    </section>
  );
}
