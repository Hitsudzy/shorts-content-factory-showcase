// Состояние карточки публикации словами (CC-0127): нет / собирается / готова / готова вашим
// решением / не готова — почему (коды `reasons` словами, иначе строка фабрики). Где не прошло
// утверждение — словами (`claims/commentary` → «комментарий»). Коды — только под «подробнее».
import type { CardStateLike } from '@/api/cards';
import type { Tone } from '@/components/common/Status';
import { dateTimeMsk } from '@/pages/batches/format';

/** Коды `reasons` (`publish_card.card_status`) словами. */
export const REASON_TEXT: Record<string, string> = {
  claims_failed: 'не прошла проверка утверждений',
  claims_not_checked: 'утверждения не проверены',
  model_refused: 'модель не написала черновик',
  no_publish_section: 'нет раздела «Публикация»',
  draft_problems: 'в черновике ошибки',
  bad_draft: 'черновик не годится',
  no_title: 'нет названия',
  no_description: 'нет описания',
  no_card: 'карточки нет',
  build_error: 'сборка сорвалась',
  error: 'сборка сорвалась',
  refused: 'фабрика отказалась собирать',
  not_asked: 'сборку не запрашивали',
};

/** Почему не готова: известные коды словами; иначе — строка фабрики; ничего — null. */
export function reasonsText(c: CardStateLike | null | undefined): string | null {
  if (!c) return null;
  const known = (c.reasons ?? []).map((r) => REASON_TEXT[r]).filter((x): x is string => !!x);
  if (known.length) return [...new Set(known)].join(', ');
  return c.why ?? null;
}

/** Где утверждение (`claims/<поле>`) словами. */
export const WHERE_TEXT: Record<string, string> = {
  commentary: 'комментарий ролика',
  hook: 'хук',
  payoff: 'развязка',
  on_screen: 'текст на экране',
  plate: 'плашка',
  title: 'название карточки',
  about: 'описание карточки',
  description: 'описание карточки',
  hashtags: 'хэштеги',
  tags: 'теги',
};

export function whereText(where: string | null | undefined): string {
  if (!where) return 'место не названо';
  const field = where.replace(/^claims\//, '');
  return WHERE_TEXT[field] ?? field;
}

export type CardView = { label: string; tone: Tone; tip: string; why: string | null };

/** Значок состояния карточки: слово, тон, подсказка; `why` — почему не готова. */
export function cardStateView(c: CardStateLike | null | undefined): CardView {
  const state = c?.state ?? 'none';
  if (state === 'none')
    return { label: 'нет карточки', tone: 'danger', tip: 'Карточки у ролика нет', why: null };
  if (state === 'building')
    return {
      label: 'собирается…',
      tone: 'live',
      tip: c?.build?.auto
        ? 'Карточку собирает фабрика сама после приёмки — состояние обновится, когда сборка закончится'
        : 'Карточку собирает фабрика — состояние обновится, когда сборка закончится',
      why: null,
    };
  if (state === 'ready')
    return { label: 'готова', tone: 'ok', tip: 'Карточка готова к публикации', why: null };
  if (state === 'ruled') {
    const r = c?.ruling;
    const when = dateTimeMsk(r?.at ?? null);
    return {
      label: 'готова вашим решением',
      tone: 'ok',
      tip: `Проверка утверждений ролика не прошла, но карточку приняли вашим решением${when ? ` ${when}` : ''}${r?.words ? `: «${r.words}»` : ''}`,
      why: null,
    };
  }
  const why = reasonsText(c);
  return {
    label: why ? `не готова: ${why}` : 'не готова',
    tone: 'warn',
    tip: why ? `Карточка не готова: ${why}` : 'Карточка не готова',
    why,
  };
}

/** Можно ли ставить в слот: готова или принята решением (`placeable`), не строгий `ready`. */
export const cardPlaceable = (c: CardStateLike | null | undefined) =>
  !!c && (c.placeable ?? (c.state === 'ready' || c.state === 'ruled'));
