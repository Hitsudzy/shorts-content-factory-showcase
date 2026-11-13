// Полоса «Ждут вас» и сетка карточек главной под батчем. Все блоки макета уже живые: «Ролики
// ждут решения» (CC-0062, ./ReelsCard) — по последнему батчу, «Фабрика спрашивает» и вопросы в
// «Ждут вас» (CC-0017, ./QuestionsCard), «Ближайшие публикации» (CC-0138, ./PublicationsCard).
import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { useQuestions } from '@/api/questions';
import { Pending, SkeletonText } from '@/components/common/Skeletons';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { attentionOf } from './attention';
import { PublicationsCard } from './PublicationsCard';
import { QuestionsCard, QuestionsCount } from './QuestionsCard';
import { ReelsCard } from './ReelsCard';
import { useWaitingReels } from './waitingReels';

/**
 * «Ждут вас»: ролики без вердикта в последнем батче и вопросы, что ждут ответа. Жёлтая полоса —
 * только когда что-то ждёт; иначе — обычная карточка «Ничего не ждёт» (CC-0137, ./attention).
 */
export function AttentionStrip() {
  const r = useWaitingReels();
  const q = useQuestions('live');
  const asked = q.data ? q.data.questions.filter((x) => x.status === 'open').length : null;
  const a = attentionOf({
    reels: {
      pending: r.isPending,
      error: !!r.error,
      none: r.none,
      waiting: r.waiting.length,
      total: r.list.data?.videos.length ?? 0,
      replaced: r.replaced,
    },
    questions: { pending: q.isPending, error: q.isError, open: asked ?? 0 },
  });
  const waiting = a.state === 'waiting';
  const variant = (to: 'videos' | 'questions') =>
    a.primary === to ? 'default' : waiting ? 'outline' : 'ghost';
  // На жёлтой полосе тёмной темы рамка второстепенной кнопки светлее — иначе сливается (CC-0138).
  const button = (to: 'videos' | 'questions') =>
    cn(
      'flex-1 sm:flex-none',
      variant(to) === 'outline' &&
        'dark:border-[color-mix(in_srgb,var(--foreground)_40%,var(--border))]',
    );
  return (
    <section
      aria-labelledby="attention-title"
      data-testid="attention"
      data-tour="attention"
      data-state={a.state}
      className={cn(
        'flex min-w-0 flex-wrap items-center gap-4 rounded-lg border px-card py-3.5',
        waiting
          ? 'border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_9%,var(--card))]'
          : 'bg-card text-card-foreground',
      )}
    >
      <strong
        id="attention-title"
        className="font-display text-[22px] font-semibold tracking-[.02em]"
      >
        {a.title}
      </strong>
      {a.state === 'loading' ? (
        <Pending label="Смотрю, что ждёт вас…" className="min-w-0 flex-1">
          <SkeletonText bare lines={1} widths={[60]} />
        </Pending>
      ) : (
        <p className="m-0 min-w-0 text-muted-foreground" data-testid="attention-text">
          {a.reels}
          {a.questions ? (
            <>
              {' '}
              <span data-testid="attention-questions">{a.questions}</span>
            </>
          ) : null}
        </p>
      )}
      <div className="flex w-full flex-wrap gap-2 sm:ml-auto sm:w-auto">
        {a.state === 'error' ? (
          <Button
            className="flex-1 sm:flex-none"
            onClick={() => {
              if (r.error) r.retry();
              if (q.isError) void q.refetch();
            }}
          >
            Повторить
          </Button>
        ) : null}
        <Button asChild variant={variant('videos')} className={button('videos')}>
          <Link to="/videos">Смотреть ролики</Link>
        </Button>
        <Button
          asChild
          variant={variant('questions')}
          className={button('questions')}
          data-variant={variant('questions')}
        >
          <Link to="/questions">
            К вопросам
            <QuestionsCount n={asked} onPrimary={variant('questions') === 'default'} />
          </Link>
        </Button>
      </div>
    </section>
  );
}

/**
 * Сетка из трёх колонок макета: ролики, вопросы, каналы, публикации — все живые: ролики (CC-0062),
 * вопросы (CC-0017), каналы (CC-0040; карточку передаёт главная в `channels`), публикации (CC-0138).
 */
export function SoonGrid({ channels }: { channels: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 md:grid-cols-3">
      <ReelsCard className="sm:col-span-2" />
      <QuestionsCard />
      {channels}
      <PublicationsCard className="sm:col-span-2" />
    </div>
  );
}
