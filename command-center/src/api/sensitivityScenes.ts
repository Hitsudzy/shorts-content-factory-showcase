// Сцены флага чувствительности (CC-0170, API CC-0169, фабрика 2.29 CF-0846): на каких сценах темы
// стоит флаг content-sensitivity. `sensitivity_scenes` — список id сцен, `"whole_topic"` (тема как
// таковая или прочитать нельзя) или null (проверки нет / строка до CF-0846 — не показываем).
// Префикс темы снимаем, как `flagged_short` у API (`factory.short_scene`): `lf-…-006-s2` → `s2`.

export type SensitivityScenes = readonly string[] | 'whole_topic' | null | undefined;

/** Id сцены без префикса темы (`<topic>-s2` → `s2`); без темы — хвост `-s2`, если он есть. */
export function shortScene(scene: string, topicId?: string | null): string {
  const pre = topicId ? `${topicId}-` : null;
  if (pre && scene.startsWith(pre) && scene.length > pre.length) return scene.slice(pre.length);
  if (!pre) {
    const m = /-(s\d+[a-z]?)$/i.exec(scene);
    if (m) return m[1]!;
  }
  return scene;
}

/** «сцена s2», «сцены s2, s3», «вся тема»; null — поле пустое (ничего не показываем). */
export function scenesText(scenes: SensitivityScenes, topicId?: string | null): string | null {
  if (scenes == null) return null;
  // Пустой список фабрика читает как всю тему (fail closed) — так же и здесь.
  if (scenes === 'whole_topic' || !Array.isArray(scenes) || scenes.length === 0) return 'вся тема';
  const ids = scenes.map((s) => shortScene(String(s), topicId));
  return `${ids.length === 1 ? 'сцена' : 'сцены'} ${ids.join(', ')}`;
}
