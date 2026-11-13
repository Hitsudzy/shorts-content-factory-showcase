import {
  autoResumeText,
  LOGIN_MISSING_TEXT,
  loginMissing,
  loginUnknown,
  loginUnknownText,
  NOT_LOGGED_IN_TEXT,
  tickParts,
} from './login';

describe('CC-0177: вход Claude словами центра', () => {
  it('три состояния: false — придержать, null — предупредить, true и старый ответ — молчать', () => {
    expect(loginMissing({ ok: false, checked: true, line: 'x' })).toBe(true);
    expect(loginUnknown({ ok: false, checked: true, line: 'x' })).toBe(false);
    expect(loginUnknown({ ok: null, checked: false, line: 'x' })).toBe(true);
    expect(loginUnknown({ checked: false, line: 'x' })).toBe(true);
    expect(loginMissing({ ok: true, checked: true, line: 'x' })).toBe(false);
    expect(loginUnknown({ ok: true, checked: true, line: 'x' })).toBe(false);
    expect(loginMissing(null)).toBe(false);
    expect(loginUnknown(undefined)).toBe(false);
  });

  it('«вход не проверен» — без повтора хвоста строки фабрики, тире по-русски', () => {
    expect(loginUnknownText('claude не найден - вход не проверен')).toBe(
      'Вход в Claude не проверен: claude не найден',
    );
    expect(loginUnknownText('вход в claude не проверялся (не корень фабрики)')).toBe(
      'Вход в claude не проверялся (не корень фабрики)',
    );
    expect(
      loginUnknownText('`claude auth status` не ответил (TimeoutExpired) - вход не проверен'),
    ).toBe('Вход в Claude не проверен: `claude auth status` не ответил (TimeoutExpired)');
    expect(loginUnknownText('')).toBe('Вход в Claude не проверен');
  });

  it('план без входа и отказ «да» — словами центра, без технической строки фабрики', () => {
    expect(LOGIN_MISSING_TEXT).toBe(
      'Claude не залогинен. Войдите — в терминале `claude`, затем `/login` — и нажмите «Проверить снова».',
    );
    expect(NOT_LOGGED_IN_TEXT).toBe(
      'Claude не залогинен. Войдите — в терминале `claude`, затем `/login` — батч не открыт.',
    );
  });

  it('обратные кавычки: код без кавычек, непарная — текстом', () => {
    expect(tickParts('в терминале `claude`, затем `/login`')).toEqual([
      { code: false, text: 'в терминале ' },
      { code: true, text: 'claude' },
      { code: false, text: ', затем ' },
      { code: true, text: '/login' },
    ]);
    expect(tickParts('без кода')).toEqual([{ code: false, text: 'без кода' }]);
    expect(tickParts('a `b` c `d')).toEqual([
      { code: false, text: 'a ' },
      { code: true, text: 'b' },
      { code: false, text: ' c `d' },
    ]);
  });

  it('`auto`: «NOT_LOGGED_IN на <stage>, <строка входа>» — стадия именем; иное — как есть', () => {
    expect(autoResumeText('NOT_LOGGED_IN на content-researcher, claude залогинен')).toBe(
      'Батч стоял на «Исследование и сценарии»: Claude был не залогинен. Тик продолжил его сам — claude залогинен.',
    );
    expect(autoResumeText('продолжен - сам')).toBe('продолжен — сам');
  });
});
