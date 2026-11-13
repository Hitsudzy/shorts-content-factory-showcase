// Буфер обмена: Clipboard API, а где его нет (не HTTPS и не localhost, запрет браузера) —
// запасной путь через выделение скрытого поля.
/** Текст — в буфер обмена; true — получилось. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // ниже — запасной путь
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const done = document.execCommand?.('copy') ?? false;
    area.remove();
    return done;
  } catch {
    return false;
  }
}
