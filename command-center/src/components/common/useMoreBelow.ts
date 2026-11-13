import { useEffect, useState } from 'react';

/** Есть ли в прокручиваемом окне текст ниже видимого (под липким подвалом). */
export function useMoreBelow(el: HTMLElement | null): boolean {
  const [below, setBelow] = useState(false);
  useEffect(() => {
    if (!el) return;
    const check = () => setBelow(el.scrollHeight - el.scrollTop - el.clientHeight > 8);
    check();
    el.addEventListener('scroll', check, { passive: true });
    const mo = typeof MutationObserver !== 'undefined' ? new MutationObserver(check) : null;
    mo?.observe(el, { childList: true, subtree: true, characterData: true });
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(check) : null;
    ro?.observe(el);
    return () => {
      el.removeEventListener('scroll', check);
      mo?.disconnect();
      ro?.disconnect();
    };
  }, [el]);
  return el ? below : false;
}
