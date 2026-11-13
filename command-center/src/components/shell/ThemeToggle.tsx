import { setTheme, useTheme } from '@/app/theme';
import { MoonIcon, SunIcon } from '@/components/common/icons';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';

/** Переключатель темы: тёмная ↔ светлая; выбор запоминается в этом браузере. */
export function ThemeToggle() {
  const theme = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';
  const label = next === 'light' ? 'Светлая тема' : 'Тёмная тема';
  return (
    <Tip content={`${label}. Выбор запомнится в этом браузере`}>
      <Button
        size="icon"
        aria-label={label}
        data-testid="theme-toggle"
        data-tour="theme"
        data-theme-current={theme}
        onClick={() => setTheme(next)}
      >
        {next === 'light' ? (
          <SunIcon className="size-[17px]" />
        ) : (
          <MoonIcon className="size-[17px]" />
        )}
      </Button>
    </Tip>
  );
}
