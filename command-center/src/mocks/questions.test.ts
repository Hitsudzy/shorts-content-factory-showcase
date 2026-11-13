import { createQuestionsBackend, routeQuestions } from './questions';

const url = (p: string) => new URL(`http://x${p}`);

describe('подставной журнал вопросов', () => {
  it('live — открытые и отвеченные, resolved — история, all — всё', () => {
    const b = createQuestionsBackend();
    const ids = (status?: string) => {
      const r = routeQuestions(
        b,
        'GET',
        url(`/api/questions${status ? `?status=${status}` : ''}`),
        null,
      );
      const body = r?.body as { status: string; questions: { id: string }[] };
      return body.questions.map((q) => q.id);
    };
    expect(ids()).toEqual(['Q6', 'Q7', 'Q8', 'Q9']);
    expect(ids('open')).toEqual(['Q6', 'Q8', 'Q9']);
    expect(ids('resolved')).toEqual(['Q3', 'Q4', 'Q5']);
    expect(ids('all')).toHaveLength(7);
  });

  it('ответ: open → answered; пустой — 422; решённый — 409; нет вопроса — 404', () => {
    const b = createQuestionsBackend();
    const post = (id: string, action: string, body: unknown) =>
      routeQuestions(b, 'POST', url(`/api/questions/${id}/${action}`), body);
    expect(post('Q9', 'answer', { text: '   ', by: 'user' })?.status).toBe(422);
    const ok = post('Q9', 'answer', { text: 'Да, взять', by: 'user' });
    expect(ok?.status).toBe(200);
    expect(ok?.body).toMatchObject({
      status: 'answered',
      answer: 'Да, взять',
      answered_by: 'user',
    });
    expect(post('Q3', 'answer', { text: 'ещё', by: 'user' })).toMatchObject({
      status: 409,
      body: { detail: 'question Q3 is already resolved' },
    });
    expect(post('Q99', 'resolve', { by: 'user' })?.status).toBe(404);
    expect(post('Q9', 'resolve', { note: 'взяли', by: 'user' })?.body).toMatchObject({
      status: 'resolved',
      note: 'взяли',
    });
    expect(post('Q9', 'resolve', { by: 'user' })?.status).toBe(409);
  });

  it('договор 0.42.0: ответ предложением (`accept`) — отказы `{detail, code}`, `accepted_suggestion`', () => {
    const b = createQuestionsBackend();
    const post = (id: string, body: unknown) =>
      routeQuestions(b, 'POST', url(`/api/questions/${id}/answer`), body);
    expect(post('Q6', { accept: true, by: 'user' })).toMatchObject({
      status: 409,
      body: { code: 'no_suggestion' },
    });
    const i = b.questions.findIndex((q) => q.id === 'Q9');
    b.questions[i] = {
      ...b.questions[i]!,
      suggestion: 'Да, взять',
      suggested_by: 'trend-hunter',
      suggested_at: '2026-10-09T10:00:00Z',
    };
    expect(post('Q9', { accept: true, text: 'Да', by: 'user' })?.status).toBe(422);
    expect(
      post('Q9', { accept: true, suggested_at: '2026-10-08T10:00:00Z', by: 'user' }),
    ).toMatchObject({ status: 409, body: { code: 'check_changed' } });
    expect(
      post('Q9', { accept: true, suggested_at: '2026-10-09T10:00:00Z', by: 'user' })?.body,
    ).toMatchObject({
      status: 'answered',
      answer: 'Да, взять',
      answered_via: 'center',
      accepted_suggestion: true,
    });
    expect(post('Q8', { text: 'своё', by: 'user', accept: false })?.body).toMatchObject({
      accepted_suggestion: false,
      answered_via: 'center',
    });
  });

  it('CC-0086: у Q8 предложение обновится перед первым «принять» — 409 check_changed, потом принято', () => {
    const b = createQuestionsBackend();
    const post = (body: unknown) =>
      routeQuestions(b, 'POST', url('/api/questions/Q8/answer'), body);
    const seen = b.questions.find((q) => q.id === 'Q8')!.suggested_at;
    expect(post({ accept: true, suggested_at: seen, by: 'user' })).toMatchObject({
      status: 409,
      body: { code: 'check_changed' },
    });
    const q8 = b.questions.find((q) => q.id === 'Q8')!;
    expect(q8.status).toBe('open');
    expect(q8.suggested_at).not.toBe(seen);
    expect(post({ accept: true, suggested_at: q8.suggested_at, by: 'user' })?.body).toMatchObject({
      status: 'answered',
      answer: q8.suggestion,
      accepted_suggestion: true,
    });
  });

  it('«только смотреть» — 409 not_working_factory, журнал не меняется', () => {
    const b = createQuestionsBackend();
    b.readOnly = true;
    const r = routeQuestions(b, 'POST', url('/api/questions/Q9/answer'), {
      text: 'да',
      by: 'user',
    });
    expect(r).toMatchObject({ status: 409, body: { code: 'not_working_factory' } });
    expect(b.questions.find((q) => q.id === 'Q9')?.status).toBe('open');
  });
});
