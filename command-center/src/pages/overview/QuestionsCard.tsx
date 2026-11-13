// «Фабрика спрашивает» главной (CC-0017): два свежих вопроса, что ждут ответа, — кто и когда
// спросил и текст; ответ — на экране «Вопросы» (кнопка «Ответить»). Тот же запрос `live`, что
// у таба и экрана: после ответа или «решено» карточка перечитывается сама. Предложенный ответ
// (CC-0086) — одной строкой под вопросом; принять его — на экране «Вопросы».
import { Link } from 'react-router';

import { useQuestions } from '@/api/questions';
import { Card, CardHead } from '@/components/common/Card';
import { CountBadge } from '@/components/common/CountBadge';
import { More } from '@/components/common/More';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { dateTimeMsk } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { liveOrder, sourceName } from '@/pages/questions/format';
import { SkeletonRows } from '@/components/common/Skeletons';

const SHOWN = 2;

/**
 * Счётчик на кнопке «К вопросам». На жёлтой главной кнопке — тёмный кружок с жёлтой цифрой:
 * жёлтый кружок на жёлтом не виден, и цифра казалась голой (CC-0138).
 */
export function QuestionsCount({
  n,
  onPrimary = false,
}: {
  n: number | null;
  onPrimary?: boolean;
}) {
  return (
    <CountBadge
      n={n}
      label="ждут ответа"
      className={cn('ml-0.5', onPrimary && 'bg-primary-foreground text-primary')}
    />
  );
}

export function QuestionsCard() {
  const q = useQuestions('live');
  const name = useChannelNames();
  const open = (q.data?.questions ?? []).filter((x) => x.status === 'open').sort(liveOrder);
  const answered = (q.data?.questions.length ?? 0) - open.length;
  return (
    <Card aria-labelledby="questions-title" data-testid="questions-card" data-tour="home-questions">
      <CardHead
        eyebrow="Вопросы"
        title="Фабрика спрашивает"
        titleId="questions-title"
        actions={
          <Button asChild variant="ghost">
            <Link to="/questions">Все вопросы</Link>
          </Button>
        }
      />
      {q.isPending ? (
        <SkeletonRows rows={2} height={304} gap={10} label="Читаю вопросы…" />
      ) : q.isError ? (
        <ErrorState title="Вопросы не прочитать" error={q.error} onRetry={() => void q.refetch()} />
      ) : !open.length ? (
        <p className="m-0 text-muted-foreground" data-testid="questions-none">
          Фабрика ничего у вас не спрашивает.
          {answered ? ` С ответом и ждут «решено»: ${answered}.` : ''}
        </p>
      ) : (
        <div className="grid gap-2.5">
          {open.slice(0, SHOWN).map((x) => (
            <div
              key={x.id}
              data-testid="questions-item"
              data-qid={x.id}
              className="grid gap-2 rounded-sm border bg-muted p-3"
            >
              <span className="text-xs text-muted-foreground">
                {[sourceName(x.source), x.channel ? name(x.channel) : null, dateTimeMsk(x.created)]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
              <p className="m-0 [overflow-wrap:anywhere]">{x.text}</p>
              {x.suggestion?.trim() ? (
                <p
                  className="m-0 truncate text-[13px] text-muted-foreground"
                  data-testid="questions-suggestion"
                  title={x.suggestion}
                >
                  Предложение: <span className="text-foreground">{x.suggestion}</span>
                </p>
              ) : null}
              <div>
                <Button asChild size="sm" variant="default">
                  <Link to="/questions">Ответить</Link>
                </Button>
              </div>
            </div>
          ))}
          {open.length > SHOWN ? (
            <p className="m-0 text-[13px] text-muted-foreground">
              Ещё {open.length - SHOWN} — на экране «Вопросы».
            </p>
          ) : null}
        </div>
      )}
      <More>
        <span>журнал вопросов: needs-you/questions.jsonl (CF-0652)</span>
        {open.map((x) => (
          <span key={x.id}>
            {x.id}: {x.source}
            {x.channel ? ` · ${x.channel}` : ''}
          </span>
        ))}
      </More>
    </Card>
  );
}
