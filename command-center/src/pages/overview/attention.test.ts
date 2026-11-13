import { attentionOf, type AttentionInput } from './attention';

const reels = (r: Partial<AttentionInput['reels']> = {}): AttentionInput['reels'] => ({
  pending: false,
  error: false,
  none: false,
  waiting: 0,
  total: 3,
  replaced: 0,
  ...r,
});
const asked = (q: Partial<AttentionInput['questions']> = {}): AttentionInput['questions'] => ({
  pending: false,
  error: false,
  open: 0,
  ...q,
});

describe('полоса «Ждут вас»: что она говорит (CC-0137)', () => {
  it('ничего не ждёт — «Ничего не ждёт», без главной кнопки', () => {
    expect(attentionOf({ reels: reels(), questions: asked() })).toEqual({
      state: 'calm',
      title: 'Ничего не ждёт',
      reels: 'В последнем батче все ролики с вердиктом.',
      questions: 'Вопросов к\u00a0вам нет.',
      primary: null,
    });
  });

  it('в последнем батче нет роликов — так и сказано, а не «все с вердиктом»', () => {
    const a = attentionOf({ reels: reels({ total: 0 }), questions: asked() });
    expect(a.state).toBe('calm');
    expect(a.title).toBe('Ничего не ждёт');
    expect(a.reels).toBe('В последнем батче роликов нет.');
  });

  it('батчей ещё не было — спокойно, без «все с вердиктом»', () => {
    const a = attentionOf({ reels: reels({ none: true, total: 0 }), questions: asked() });
    expect(a.state).toBe('calm');
    expect(a.reels).toBe('Батчей ещё не было — роликов на приёмке нет.');
  });

  it('ролики без вердикта — «Ждут вас», главная кнопка — ролики', () => {
    const a = attentionOf({ reels: reels({ waiting: 2 }), questions: asked({ open: 3 }) });
    expect(a).toEqual({
      state: 'waiting',
      title: 'Ждут вас',
      reels: 'Роликов без вердикта в последнем батче: 2.',
      questions: 'Вопросов ждут вашего ответа: 3.',
      primary: 'videos',
    });
  });

  it('ждут только вопросы — главная кнопка «К вопросам»', () => {
    const a = attentionOf({ reels: reels(), questions: asked({ open: 1 }) });
    expect(a.state).toBe('waiting');
    expect(a.title).toBe('Ждут вас');
    expect(a.primary).toBe('questions');
  });

  it('ролики ждут, вопросы ещё идут — «Ждут вас», про вопросы — где смотреть', () => {
    const a = attentionOf({ reels: reels({ waiting: 1 }), questions: asked({ pending: true }) });
    expect(a.state).toBe('waiting');
    expect(a.questions).toBe('Вопросы к\u00a0вам\u00a0— на экране «Вопросы».');
  });

  it('данные ещё идут — нейтрально, без «Ждут вас» и без «Ничего не ждёт»', () => {
    for (const input of [
      { reels: reels({ pending: true }), questions: asked() },
      { reels: reels(), questions: asked({ pending: true }) },
    ]) {
      const a = attentionOf(input);
      expect(a.state).toBe('loading');
      expect(a.title).toBe('Что ждёт вас');
      expect(a.primary).toBeNull();
    }
  });

  it('вопросы не прочитались — не «Ничего не ждёт», а честно: не удалось', () => {
    const a = attentionOf({ reels: reels(), questions: asked({ error: true }) });
    expect(a.state).toBe('error');
    expect(a.title).toBe('Что ждёт вас');
    expect(a.reels).toBe('В последнем батче все ролики с вердиктом.');
    expect(a.questions).toBe('Не удалось прочитать вопросы.');
    expect(a.primary).toBeNull();
  });

  it('ролики не прочитались, а вопросы ждут — всё равно «Ждут вас»', () => {
    const a = attentionOf({ reels: reels({ error: true }), questions: asked({ open: 2 }) });
    expect(a.state).toBe('waiting');
    expect(a.reels).toBe('Не удалось прочитать ролики.');
    expect(a.primary).toBe('questions');
  });

  it('не прочиталось ничего — одна строка, без «Ничего не ждёт»', () => {
    const a = attentionOf({ reels: reels({ error: true }), questions: asked({ error: true }) });
    expect(a.state).toBe('error');
    expect(a.reels).toBe('Не удалось прочитать ни ролики, ни вопросы.');
    expect(a.questions).toBe('');
  });
});
