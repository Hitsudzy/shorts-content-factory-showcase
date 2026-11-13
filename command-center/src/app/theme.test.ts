import { applyTheme, readSavedTheme, resetTheme, setTheme, THEME_STORAGE_KEY } from './theme';

describe('тема', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    applyTheme('dark');
  });

  it('по умолчанию тёмная', () => {
    expect(readSavedTheme()).toBe('dark');
  });

  it('светлая запоминается и ставит data-theme на <html>', () => {
    setTheme('light');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(readSavedTheme()).toBe('light');
  });

  it('сброс забывает выбор и возвращает тёмную', () => {
    setTheme('light');
    resetTheme();
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('без доступа к хранилищу — тёмная и без падения', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    expect(readSavedTheme()).toBe('dark');
    expect(() => setTheme('light')).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
