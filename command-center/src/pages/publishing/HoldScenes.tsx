// Сцены флага чувствительности у строки холда (CC-0170): «сцены s2, s3» / «вся тема».
import type { HoldRow } from '@/api/publish';
import { scenesText } from '@/api/sensitivityScenes';

/** Сцены флага чувствительности строки холда: «сцены s2, s3» / «вся тема»; null — не показываем. */
export function HoldScenes({ hold }: { hold: Pick<HoldRow, 'sensitivity_scenes' | 'topic_id'> }) {
  const text = scenesText(hold.sensitivity_scenes, hold.topic_id);
  if (!text) return null;
  return (
    <span
      className="text-xs text-muted-foreground [overflow-wrap:anywhere]"
      data-testid="hold-scenes"
    >
      флаг чувствительности: {text}
    </span>
  );
}
