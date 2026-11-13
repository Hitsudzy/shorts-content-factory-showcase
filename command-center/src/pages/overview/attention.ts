// Полоса «Ждут вас» главной (CC-0137): что она говорит — по роликам последнего батча и
// вопросам без ответа. «Ждут вас» с жёлтой рамкой — только когда что-то правда ждёт; ничего не
// ждёт — «Ничего не ждёт», обычная карточка; данные ещё идут или не прочитались — нейтрально,
// без «Ничего не ждёт» (иначе полоса обещала бы то, чего центр не знает).
import { nbDashes } from '@/api/humanText';
import { questionsLine } from '@/pages/questions/format';

export type AttentionState = 'loading' | 'waiting' | 'calm' | 'error';

export type AttentionInput = {
  reels: {
    pending: boolean;
    error: boolean;
    /** Батчей ещё не было. */
    none: boolean;
    /** Роликов последнего батча без вердикта. */
    waiting: number;
    /** Роликов в последнем батче всего. */
    total: number;
    /** Без вердикта, но заменены принятой пересборкой (CC-0088). */
    replaced: number;
  };
  questions: { pending: boolean; error: boolean; open: number };
};

export type Attention = {
  state: AttentionState;
  title: string;
  /** Строка о роликах (с точкой). */
  reels: string;
  /** Строка о вопросах (с точкой). */
  questions: string;
  /** Главная кнопка полосы; `null` — обе кнопки второстепенные. */
  primary: 'videos' | 'questions' | null;
};

const TITLES: Record<AttentionState, string> = {
  waiting: 'Ждут вас',
  calm: 'Ничего не ждёт',
  loading: 'Что ждёт вас',
  error: 'Что ждёт вас',
};

function reelsLine(r: AttentionInput['reels']): string {
  if (r.error) return 'Не удалось прочитать ролики.';
  if (r.pending) return 'Ролики на приёмке — на экране «Ролики».';
  if (r.none) return 'Батчей ещё не было — роликов на приёмке нет.';
  if (r.waiting) return `Роликов без вердикта в последнем батче: ${r.waiting}.`;
  if (!r.total) return 'В последнем батче роликов нет.';
  if (r.replaced) return 'В последнем батче решения не ждёт ни один ролик.';
  return 'В последнем батче все ролики с вердиктом.';
}

function questionsText(q: AttentionInput['questions']): string {
  if (q.error) return 'Не удалось прочитать вопросы.';
  return questionsLine(q.pending ? null : q.open);
}

/** Что говорит полоса: состояние, заголовок, строки и главная кнопка. */
export function attentionOf({ reels, questions }: AttentionInput): Attention {
  const videosWait = !reels.pending && !reels.error && reels.waiting > 0;
  const questionsWait = !questions.pending && !questions.error && questions.open > 0;
  const state: AttentionState =
    videosWait || questionsWait
      ? 'waiting'
      : reels.error || questions.error
        ? 'error'
        : reels.pending || questions.pending
          ? 'loading'
          : 'calm';
  const both = state === 'error' && reels.error && questions.error;
  return {
    state,
    title: TITLES[state],
    reels: both ? 'Не удалось прочитать ни ролики, ни вопросы.' : nbDashes(reelsLine(reels)),
    questions: both ? '' : nbDashes(questionsText(questions)),
    primary: state !== 'waiting' ? null : videosWait ? 'videos' : 'questions',
  };
}
