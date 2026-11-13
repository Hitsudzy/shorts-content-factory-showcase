// Подставные записи публикации (src/mocks/publishWrites.ts) держат форму фабрики: план ничего не
// пишет и даёт токен, «да» сжигает его при любом исходе, кроме `busy`; токен чужого действия —
// `confirm_mismatch`; мир сменился — `check_changed`; модельный путь — `model_refused`.
import { getApiUpload, getHolds, getNote, getPause, getQueue, getStudio } from '@/api/publish';
import { BatchError, problemCode } from '@/api/batchProblem';
import {
  apiSwitch,
  cardBuild,
  cardPlace,
  holdSign,
  planHoldSign,
  planApiSwitch,
  planStudioRecord,
  planUpload,
  studioRecord,
  upload,
  pauseClear,
  pauseSet,
  planCardBuild,
  planCardPlace,
  planPauseClear,
  planPauseSet,
  planRotationAssign,
  planRotationRefuse,
  planRotationReject,
  rotationReject,
  rotationRefuse,
  type PlannedSlot,
  type Ruling,
} from '@/api/publishWrites';

import { publish } from './handlers';
import { AUDIT_PHRASE } from './publishWrites';
import {
  DEFICIT,
  HOLD_RESOLVED,
  HOLD_RIGHTS,
  HOLD_SENSITIVE,
  NOT_READY,
  PLACED,
  READY,
  REEL,
  REEL_BATCH,
  SCIENCE,
  SCRIPT_HELD,
  SCRIPT_REJECTED,
  SCRIPT_STANDING,
  TECH,
  WAITING,
} from './publish';

const code = async (p: Promise<unknown>) => {
  try {
    await p;
  } catch (e) {
    expect(e).toBeInstanceOf(BatchError);
    return problemCode(e);
  }
  throw new Error('ждали отказ');
};

const REASON = 'проверка — смотрим вкладку «Авторские права»';
const DRAFT = { title: 'Rapid 11', about: 'Example Pictures moved it', hashtags: ['RR11'], tags: ['RR'] };

describe('подставные записи публикации', () => {
  it('пауза: план → «да» → пауза стоит; тот же токен второй раз — confirm_unknown', async () => {
    const plan = await planPauseSet(REEL, { reason: REASON, until: '2026-10-20' });
    expect(plan).toMatchObject({ ok: true, action: 'pause_set', expires_in_s: 120 });
    expect(plan.row).toMatchObject({ reason: `${REASON} (из центра)` });
    expect((await getPause(REEL)).state).toBe('free');
    const done = await pauseSet(REEL, plan.confirm!);
    expect(done.row.until).toBe('2026-10-20T00:00:00+03:00');
    expect((await getPause(REEL)).state).toBe('paused');
    expect(await code(pauseSet(REEL, plan.confirm!))).toBe('confirm_unknown');
    // уже стоит — без замены нельзя, с заменой можно; причина обязательна
    expect((await planPauseSet(REEL, { reason: REASON })).ok).toBe(false);
    expect((await planPauseSet(REEL, { reason: REASON, replace: true })).ok).toBe(true);
    expect(await code(planPauseSet(REEL, { reason: '  ' }))).toBe('note_required');
    expect(await code(planPauseSet(REEL, { reason: REASON, until: 'завтра' }))).toBe('invalid');
  });

  it('токен не тому действию сгорает; busy токен бережёт; срок истёк — confirm_expired', async () => {
    const set = await planPauseSet(REEL, { reason: REASON });
    expect(await code(pauseClear(REEL, set.confirm!))).toBe('confirm_mismatch');
    expect(await code(pauseSet(REEL, set.confirm!))).toBe('confirm_unknown');

    const clear = await planPauseClear(SCIENCE, { note: 'канал запущен' });
    expect(clear.ok).toBe(true);
    publish.writes.state.next = 'busy';
    expect(await code(pauseClear(SCIENCE, clear.confirm!))).toBe('busy');
    const done = await pauseClear(SCIENCE, clear.confirm!);
    expect(done.row.clear_note).toBe('канал запущен (из центра)');
    expect((await planPauseClear(SCIENCE, {})).ok).toBe(false);

    publish.writes.state.life = 0;
    const late = await planPauseSet(SCIENCE, { reason: REASON });
    expect(await code(pauseSet(SCIENCE, late.confirm!))).toBe('confirm_expired');
    expect(publish.writes.state.written.map((w) => w.action)).toEqual(['pause_clear']);
  });

  it('карточка в слот: слот, предупреждения и сдвиги; мир сменился — check_changed', async () => {
    publish.writes.state.placeMoves = true;
    const body = { batch_id: '2026-10-09T0200Z', dir: 'example-film', slug: WAITING };
    const plan = await planCardPlace(REEL, body);
    const slot = plan.slot as unknown as PlannedSlot;
    expect(plan.ok).toBe(true);
    expect(slot.warnings[0]).toContain('WINDOW');
    expect(slot.moves).toHaveLength(1);
    // между планом и «да» канал встал на паузу: слот пропал — план уже другой
    const p = await planPauseSet(REEL, { reason: REASON });
    await pauseSet(REEL, p.confirm!);
    expect(await code(cardPlace(REEL, plan.confirm!))).toBe('check_changed');
    const paused = await planCardPlace(REEL, body);
    expect(paused.paused).toContain('paused');
    const c = await planPauseClear(REEL, {});
    await pauseClear(REEL, c.confirm!);
    const again = await planCardPlace(REEL, body);
    const done = await cardPlace(REEL, again.confirm!);
    expect(done.report[0]).toContain(`${WAITING}: _queue ->`);
    const q = await getQueue(REEL);
    expect(q.waiting).toEqual([]);
    expect(q.slots.some((s) => s.taken_by === WAITING)).toBe(true);
    // неготовая карточка не идёт; чужой ролик — 404
    expect((await planCardPlace(REEL, { ...body, slug: NOT_READY })).ok).toBe(false);
    expect(await code(planCardPlace(REEL, { ...body, slug: 'nope' }))).toBe('unknown_video');
  });

  it('сборка карточки: модель — model_refused; черновик плох — ok:false; собрана — not_ready', async () => {
    const at = { batch_id: '2026-10-09T0200Z', dir: 'example-film', slug: WAITING };
    expect(await code(planCardBuild(REEL, { ...at, draft: DRAFT, model: true }))).toBe(
      'model_refused',
    );
    expect(await code(planCardBuild(REEL, { ...at, draft: null }))).toBe('model_refused');
    const bad = await planCardBuild(REEL, { ...at, draft: { ...DRAFT, title: '' } });
    expect(bad).toMatchObject({ ok: false, confirm: null });
    expect(bad.why).toContain('title');
    const plan = await planCardBuild(REEL, { ...at, draft: DRAFT });
    expect(plan.out).toBe(`pipeline/${REEL_BATCH}/work/publish-card/${WAITING}.md`);
    const done = await cardBuild(REEL, plan.confirm!);
    expect(done.status).toBe('not_ready');
    expect(done.mark).toMatchObject({ why: 'claims_not_checked' });
  });

  it('ротация: вердикт в плане, отказ за нехваткой, канал без ротации — rotation_broken', async () => {
    const up = await planRotationReject(REEL, { script_id: SCRIPT_STANDING, reason: REASON });
    expect((up.ruling as Ruling).verdict).toBe('upheld');
    const done = await rotationReject(REEL, up.confirm!);
    expect(done.result).toMatchObject({ verdict: 'upheld' });
    const no = await planRotationReject(REEL, { script_id: SCRIPT_REJECTED, reason: REASON });
    expect(no).toMatchObject({ ok: true, verdict: 'denied' });
    expect(
      (await planRotationReject(REEL, { script_id: SCRIPT_REJECTED, reason: 'коротко' })).ok,
    ).toBe(false);

    const held = await planRotationAssign(REEL, { batch_id: 'b', script_ids: [SCRIPT_HELD] });
    expect(held.ok).toBe(false);
    const despite = await planRotationAssign(REEL, {
      batch_id: 'b',
      script_ids: [SCRIPT_HELD],
      despite_shortage: true,
    });
    expect(despite.ok).toBe(true);

    expect(
      await code(
        planRotationRefuse(REEL, { script_id: SCRIPT_REJECTED, reason: REASON, deficit: 'x.json' }),
      ),
    ).toBe('invalid');
    const refuse = await planRotationRefuse(REEL, {
      script_id: SCRIPT_REJECTED,
      reason: REASON,
      deficit: DEFICIT,
    });
    expect(refuse.ok).toBe(true);
    await rotationRefuse(REEL, refuse.confirm!);
    expect(await code(planRotationAssign(TECH, { batch_id: 'b', script_ids: ['s'] }))).toBe(
      'rotation_broken',
    );
  });

  it('API не на рабочей фабрике — not_working_factory; factory_broken — 500', async () => {
    const plan = await planPauseSet(REEL, { reason: REASON });
    publish.writes.state.next = 'factory_broken';
    expect(await code(pauseSet(REEL, plan.confirm!))).toBe('factory_broken');
    publish.writes.state.readOnly = true;
    expect(await code(planPauseSet(REEL, { reason: REASON }))).toBe('not_working_factory');
  });
});

describe('CC-0069: переключатель, загрузка, запись Studio', () => {
  const NOTE = 'решили на созвоне 11.10 после аудита YouTube API';

  async function switchOn(channel = REEL) {
    const plan = await planApiSwitch(channel, { on: true, note: NOTE });
    return apiSwitch(channel, plan.confirm!, AUDIT_PHRASE);
  }

  it('включение: без заметки — note_required; план с предупреждениями и фразой', async () => {
    expect(await code(planApiSwitch(REEL, { on: true }))).toBe('note_required');
    const plan = await planApiSwitch(REEL, { on: true, note: NOTE });
    expect(plan.ok).toBe(true);
    expect(plan.audit_phrase).toBe(AUDIT_PHRASE);
    expect(plan.warnings?.length).toBeGreaterThan(0);
    expect(plan.row).toMatchObject({ on: true, note: `${NOTE} (из центра)` });
    const off = await planApiSwitch(REEL, { on: false });
    expect(off.ok).toBe(false);
    expect(off.why).toMatch(/уже выключена/);
    expect(off.confirm).toBeNull();
    const stub = await planApiSwitch(SCIENCE, { on: true, note: NOTE });
    expect(stub.ok).toBe(false);
    expect(stub.why).toMatch(/нечего грузить/);
  });

  it('фраза не та — audit_unconfirmed и токен сгорел; та — включено, GET видит', async () => {
    const plan = await planApiSwitch(REEL, { on: true, note: NOTE });
    expect(await code(apiSwitch(REEL, plan.confirm!, 'аудит'))).toBe('audit_unconfirmed');
    expect(await code(apiSwitch(REEL, plan.confirm!, AUDIT_PHRASE))).toBe('confirm_unknown');
    expect(publish.writes.state.written).toEqual([]);
    const done = await switchOn();
    expect(done).toMatchObject({ action: 'api_upload_switch', on: true, changed: true });
    expect((await getApiUpload(REEL)).channels[0]!.on).toBe(true);
    // выключение — без фразы
    const off = await planApiSwitch(REEL, { on: false });
    expect(off.audit_phrase).toBeNull();
    expect((await apiSwitch(REEL, off.confirm!, null)).on).toBe(false);
  });

  it('файл переключателя не читается — 409 switch_unreadable', async () => {
    publish.writes.state.switchBroken = 'Expecting value: line 1 column 1';
    expect(await code(planApiSwitch(REEL, { on: true, note: NOTE }))).toBe('switch_unreadable');
  });

  it('загрузка: выключено — why фабрики без токена; включено — сводка, условия, вопрос', async () => {
    const offPlan = await planUpload(REEL, { slug: READY });
    expect(offPlan.ok).toBe(false);
    expect(offPlan.why).toMatch(/API-загрузка выключена/);
    expect(offPlan.confirm).toBeNull();
    await switchOn();
    const plan = await planUpload(REEL, { slug: READY });
    expect(plan.ok).toBe(true);
    expect(plan.summary).toMatch(/Название:/);
    expect(plan.tos_notice).toMatch(/Условия использования YouTube/);
    expect(plan.question).toMatch(/Введите «да»/);
    expect(await code(planUpload(REEL, { slug: 'нет-такого' }))).toBe('unknown_note');
    expect((await planUpload(REEL, { slug: PLACED })).why).toMatch(/уже загружен/);
    expect((await planUpload(REEL, { slug: NOT_READY })).why).toMatch(/карточка не готова/);
    publish.writes.state.channelId = '';
    const noId = await planUpload(REEL, { slug: READY });
    expect(noId.why).toMatch(/PUBLISHER_CHANNEL_ID/);
    expect(noId.confirm).toBeNull();
  });

  it('ответ не «да» — answer_required, токен цел; «да» — загружено', async () => {
    await switchOn();
    const plan = await planUpload(REEL, { slug: READY });
    expect(await code(upload(REEL, plan.confirm!, 'ок'))).toBe('answer_required');
    expect(await code(upload(REEL, plan.confirm!, ''))).toBe('answer_required');
    const done = await upload(REEL, plan.confirm!, ' Да ');
    expect(done).toMatchObject({ action: 'api_upload', slug: READY });
    expect(done.row).toMatchObject({ source: 'api' });
    expect(publish.writes.state.calls.at(-1)!.body).toEqual({
      confirm: plan.confirm,
      answer: ' Да ',
    });
  });

  it('загрузка упала: reauthorize, upload_failed, uploaded_unrecorded — строки «внести руками»', async () => {
    await switchOn();
    for (const outcome of ['reauthorize', 'upload_failed', 'uploaded_unrecorded'] as const) {
      const plan = await planUpload(REEL, { slug: READY });
      publish.writes.state.uploadNext = outcome;
      const e = await upload(REEL, plan.confirm!, 'да').catch((x: unknown) => x);
      expect(problemCode(e)).toBe(outcome);
      if (outcome === 'uploaded_unrecorded') {
        expect((e as BatchError).status).toBe(500);
        expect((e as BatchError).problem!.details.some((d) => d.startsWith('MANUAL'))).toBe(true);
      }
    }
  });

  it('запись Studio: расхождения — ok:false; совпало — would-add и серия растёт; повтор — exists', async () => {
    const note = await getNote(REEL, READY, null);
    const f = note.studio!;
    const read = {
      title: f.title,
      description: f.description,
      tags: f.tags_input,
      visibility: 'Запланировано',
      publish_at: (f.schedule as { publish_at: string }).publish_at,
    };
    const wrong = await planStudioRecord(REEL, {
      slug: READY,
      video_id: 'Ab3dE5gH7jK',
      read: { ...read, title: 'другое', tags: 'Zenith' },
    });
    expect(wrong.ok).toBe(false);
    expect(wrong.mismatches.map((m) => m.field)).toEqual(['title', 'tags']);
    expect(wrong.confirm).toBeNull();
    const plan = await planStudioRecord(REEL, { slug: READY, video_id: 'Ab3dE5gH7jK', read });
    expect(plan.ok).toBe(true);
    expect(plan.status).toBe('would-add');
    const before = (await getStudio(REEL)).streak.streak;
    const done = await studioRecord(REEL, plan.confirm!);
    expect(done).toMatchObject({ status: 'added', slug: READY });
    expect(done.streak.streak).toBe(before + 1);
    const again = await planStudioRecord(REEL, { slug: READY, video_id: 'Ab3dE5gH7jK', read });
    expect(again.status).toBe('exists');
    expect(again.ok).toBe(false);
    expect(
      await code(planStudioRecord(REEL, { slug: READY, video_id: 'x', read: [] as never })),
    ).toBe('invalid');
  });
});

describe('CC-0071: подпись холда', () => {
  it('GET холдов: signable и строка отказа фабрики у каждой строки', async () => {
    const h = await getHolds(REEL);
    expect(h.open).toHaveLength(2);
    const by = (t: string) => h.rows.find((r) => r.topic_id === t)!;
    expect(by(HOLD_SENSITIVE.topic_id)).toMatchObject({ signable: true, sign_refusal: null });
    expect(by(HOLD_RIGHTS.topic_id)).toMatchObject({
      signable: false,
      sign_refusal: { code: 'not_signable' },
    });
    expect(by(HOLD_RESOLVED.topic_id).sign_refusal?.code).toBe('already_signed');
  });

  it('план → «да»: подпись из центра, холд уходит из открытых', async () => {
    const plan = await planHoldSign(REEL, HOLD_SENSITIVE, 'посмотрел: кадры без крупных планов');
    expect(plan).toMatchObject({
      ok: true,
      action: 'hold_sign',
      expires_in_s: 120,
      note: 'посмотрел: кадры без крупных планов',
      signature: { user: 'user', via: 'center' },
    });
    expect(plan.flagged.some((f) => f.includes('чувствительность контента'))).toBe(true);
    expect(publish.writes.state.written).toHaveLength(0);
    const done = await holdSign(REEL, HOLD_SENSITIVE, plan.confirm!);
    expect(done.row.signature).toMatchObject({ via: 'center', note: plan.note });
    expect(done.holds.open.map((r) => r.topic_id)).toEqual([HOLD_RIGHTS.topic_id]);
    expect((await getHolds(REEL)).open).toHaveLength(1);
    // Второй раз — фабрика отказывает словами.
    expect(await code(planHoldSign(REEL, HOLD_SENSITIVE, 'ещё раз'))).toBe('already_signed');
  });

  it('отказы плана: без заметки, не тот холд, нет холда, реестр не читается', async () => {
    expect(await code(planHoldSign(REEL, HOLD_SENSITIVE, '  '))).toBe('empty_note');
    expect(await code(planHoldSign(REEL, HOLD_RIGHTS, 'заметка'))).toBe('not_signable');
    expect(await code(planHoldSign(REEL, HOLD_RESOLVED, 'заметка'))).toBe('already_signed');
    expect(await code(planHoldSign(REEL, { batch_id: 'x', topic_id: 'y' }, 'заметка'))).toBe(
      'no_such_hold',
    );
    publish.state.holdsProblem = 'publish/publication-holds.json: not JSON';
    expect(await code(planHoldSign(REEL, HOLD_SENSITIVE, 'заметка'))).toBe('ledger_unreadable');
  });

  it('«да»: подписали в терминале — already_signed; токен другого холда — confirm_mismatch', async () => {
    const plan = await planHoldSign(REEL, HOLD_SENSITIVE, 'заметка');
    expect(await code(holdSign(REEL, HOLD_RIGHTS, plan.confirm!))).toBe('confirm_mismatch');
    const again = await planHoldSign(REEL, HOLD_SENSITIVE, 'заметка');
    publish.state.holds.find((r) => r.topic_id === HOLD_SENSITIVE.topic_id)!.signature = {
      user: 'user',
      via: 'terminal',
    };
    expect(await code(holdSign(REEL, HOLD_SENSITIVE, again.confirm!))).toBe('already_signed');
    publish.writes.state.readOnly = true;
    expect(await code(planHoldSign(REEL, HOLD_SENSITIVE, 'заметка'))).toBe('not_working_factory');
  });
});
