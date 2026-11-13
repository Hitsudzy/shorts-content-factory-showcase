// Правка списков канала и сборка концовки на вкладке «Данные канала» (CC-0115 шаг 3 → CC-0114
// API). «Править список…» — у партнёрских ссылок, вашей части блок-листа и источников фактов
// (CC-0129) и происхождения футажа (CC-0130) — по строкам: поля схемы списка с подписями,
// добавить/убрать, проверка словами (./RowsEditor, ./listSchemas); документ как файл — только под
// «Подробнее → как файл». План фабрики показывает, изменится ли файл и что не прошло её проверку (у источников фактов —
// словами); «да» набираете вы. Правка начата с того `sha256`, что был при открытии: файл с
// тех пор сменился — «Список изменился, откройте заново» (свернуть и раскрыть — правка начнётся
// со свежего файла). «Собрать концовку…» — план фабрики (что нужно для рендера, есть ли всё,
// не идёт ли батч) → «да»; рендер идёт отдельно, ответ — сразу. Пути, коды и строки фабрики —
// под «подробнее».
import { useId, useState } from 'react';

import {
  LIST_CHANGED,
  listProblemText,
  planEnding,
  planList,
  renderEnding,
  useAfterChannelListWrite,
  writeList,
  type ChannelListPlan,
  type ChannelListWriteResult,
  type EndingRenderPlan,
  type EndingRenderResult,
  type ListKind,
} from '@/api/channelLists';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';
import { Disclosure, Done, PlanHead, WriteAction } from '@/pages/publishing/Writes';

import { KNOWN_KINDS, kindText, tierLabel } from './channelDataWords';
import {
  ACCEPTED_FIELDS,
  ANY_HOST_FIELDS,
  aiPolicyText,
  channelFields,
  factDoc,
  factLineText,
  factProblems,
  factRowsOf,
  footageDoc,
  footageLineText,
  footageProblems,
  footageRowsOf,
  foundByText,
  licenceName,
  LICENCE_WORDS,
  newAccepted,
  newAdded,
  newAnyHost,
  newChannel,
  newOfficial,
  newOrigin,
  newOutlet,
  newRefused,
  officialFields,
  originFields,
  originName,
  OUTLET_FIELDS,
  PROGRAMME_FIELDS,
  productFields,
  productProblems,
  programmeProblems,
  REFUSED_FIELDS,
  REFUSED_WORDS,
  withOnScreen,
} from './listSchemas';
import { itemsOf, rowOf, type Item, type Row } from './rows';
import { RowsEditor } from './RowsEditor';
import { inputBase } from './styles';

const LIST_WORDS: Record<ListKind, { what: string; empty: Record<string, unknown> }> = {
  'fact-sources': { what: 'источники фактов', empty: { tiers: { '1': [], '2': [] } } },
  'footage-origin': { what: 'происхождение футажа', empty: {} },
  affiliate: { what: 'партнёрские ссылки', empty: { programmes: [], products: [] } },
};

function ChangedNote() {
  return (
    <p
      role="status"
      data-testid="list-changed"
      className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] p-3 font-semibold"
    >
      {LIST_CHANGED}: сверните правку и раскройте её снова — она начнётся со свежего файла.
    </p>
  );
}

/** Строка проверки фабрики → словами; не узнали — null (остаётся под «подробнее»). */
type Say = (line: string) => string | null;

function ListPlanView({ plan, say }: { plan: ChannelListPlan; say?: Say }) {
  const changed = plan.refusals.some((r) => r.code === 'check_changed');
  const invalid = plan.refusals.filter((r) => r.code === 'invalid');
  const said = say
    ? [...new Set(invalid.map((r) => say(r.line)).filter((t): t is string => !!t))]
    : [];
  const unsaid = say ? invalid.filter((r) => !say(r.line)).length : invalid.length;
  return (
    <>
      <PlanHead plan={plan} yes="можно записать" no="записать нельзя" />
      {changed ? <ChangedNote /> : null}
      {plan.ok ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="list-plan-changes">
          <StatusBadge tone={plan.changes ? 'warn' : 'idle'}>
            {plan.changes ? 'изменится' : 'без изменений'}
          </StatusBadge>
          <span>
            {plan.changes
              ? 'Файл списка перепишется вашим документом — фабрика сохранит его в своей истории.'
              : 'Документ совпадает с файлом — записывать нечего.'}
          </span>
        </div>
      ) : null}
      {invalid.length ? (
        <div className="grid gap-1" data-testid="list-plan-invalid">
          <p className="m-0 text-danger">
            {said.length
              ? 'Фабрика нашла ошибки в списке:'
              : 'Фабрика нашла ошибки в списке — что именно, под «подробнее».'}
          </p>
          {said.length ? (
            <ul
              className="m-0 grid list-disc gap-0.5 pl-5 text-danger"
              data-testid="list-plan-invalid-lines"
            >
              {said.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          ) : null}
          {said.length && unsaid ? (
            <p className="m-0 text-xs text-muted-foreground">Ещё {unsaid} — под «подробнее».</p>
          ) : null}
        </div>
      ) : null}
      <More className="mt-0">
        <span>
          {plan.action} · {plan.channel} · by {plan.by} · via {plan.via}
        </span>
        {plan.path ? <span>файл: {plan.path}</span> : null}
        <span>
          было: {plan.base_sha256 ?? 'файла нет'} · сейчас: {plan.sha256 ?? 'файла нет'} · станет:{' '}
          {plan.new_sha256 ?? 'без записи'}
        </span>
        {plan.refusals.map((r, i) => (
          <span key={i}>
            {r.code}: {r.line}
          </span>
        ))}
        {plan.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
      </More>
    </>
  );
}

type EditorProps = {
  channel: string;
  kind: ListKind;
  doc: unknown;
  sha: string | null;
  onDone: (r: ChannelListWriteResult) => void;
};

/** Сегодня по Москве: день, которым фабрика помечает новую запись (`added_at`). */
const todayMsk = () => new Date(Date.now() + 3 * 3600_000).toISOString().slice(0, 10);

const nonEmpty = (p: string[][]) => p.reduce((n, x) => n + (x.length ? 1 : 0), 0);

/** «Записать…» под правкой: план с sha чтения → «да». */
function ListWrite({
  channel,
  kind,
  value,
  base,
  why,
  say,
  onDone,
}: {
  channel: string;
  kind: ListKind;
  value: Record<string, unknown> | Record<string, unknown>[] | null;
  base: string | null;
  why: string | null;
  say?: Say;
  onDone: (r: ChannelListWriteResult) => void;
}) {
  const after = useAfterChannelListWrite(channel);
  return (
    <WriteAction
      id={`list-${kind}`}
      label="Показать план…"
      title={`Записать ${LIST_WORDS[kind].what}?`}
      description="Фабрика проверила список — вот что будет с файлом канала."
      body={value && !why ? { value, base_sha256: base } : null}
      why={why}
      tip="Фабрика проверит и покажет план; запишет — после вашего «да»"
      confirmLabel="Записать"
      pendingLabel="Записываю…"
      yes
      plan={(b) => planList(channel, kind, b)}
      act={(c) => writeList(channel, kind, c)}
      view={(plan) => <ListPlanView plan={plan} say={say} />}
      problemText={listProblemText}
      onSettled={after}
      onDone={onDone}
    />
  );
}

/** Документ, который уйдёт фабрике, — как файл (только смотреть). */
function AsFile({ kind, value }: { kind: ListKind; value: unknown }) {
  return (
    <More className="mt-0" label="Подробнее → как файл">
      <pre
        data-testid={`list-${kind}-file`}
        className="m-0 max-h-72 overflow-auto rounded-sm bg-muted p-2 font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere]"
      >
        {JSON.stringify(value, null, 2)}
      </pre>
    </More>
  );
}

function RowsWhy({ kind, why }: { kind: ListKind; why: string | null }) {
  return why ? (
    <span className="text-xs text-danger" data-testid={`list-${kind}-why`}>
      {why}
    </span>
  ) : null;
}

const bad = (n: number) =>
  n ? `Поправьте записи, отмеченные красным (${n}) — план спросим, когда всё в порядке` : null;

/** Партнёрские ссылки — программы и товары по строкам; прочие поля документа — как были. */
function AffiliateEditor({ channel, doc, sha, onDone }: EditorProps) {
  const [base] = useState(sha);
  const d = (doc && typeof doc === 'object' ? doc : LIST_WORDS.affiliate.empty) as Row;
  const [progs, setProgs] = useState<Item[]>(() => itemsOf(d.programmes, PROGRAMME_FIELDS));
  const progRows = progs.map((x) => rowOf(x, PROGRAMME_FIELDS));
  const fields = productFields(progRows);
  const [prods, setProds] = useState<Item[]>(() => itemsOf(d.products, fields));
  const prodRows = prods.map((x) => rowOf(x, fields));
  const pp = programmeProblems(progRows);
  const dp = productProblems(prodRows, progRows);
  const why = bad(nonEmpty(pp) + nonEmpty(dp));
  const value = { ...d, programmes: progRows, products: prodRows };
  return (
    <>
      <RowsEditor
        id="programmes"
        title="Программы"
        items={progs}
        fields={PROGRAMME_FIELDS}
        onChange={setProgs}
        problems={pp}
        newRow={() => newAdded(todayMsk())}
        addLabel="Добавить программу"
        rowName={(x, i) => x.text.name?.trim() || `Программа ${i + 1}`}
      />
      <RowsEditor
        id="products"
        title="Товары и ссылки"
        items={prods}
        fields={fields}
        onChange={setProds}
        problems={dp}
        newRow={() => newAdded(todayMsk())}
        addLabel="Добавить товар"
        rowName={(x, i) => x.text.names?.split(',')[0]?.trim() || `Товар ${i + 1}`}
      />
      <RowsWhy kind="affiliate" why={why} />
      <AsFile kind="affiliate" value={value} />
      <div>
        <ListWrite
          channel={channel}
          kind="affiliate"
          value={value}
          base={base}
          why={why}
          onDone={onDone}
        />
      </div>
    </>
  );
}

/** Виды фактов канала (`kinds[]`) словами: убрать, добавить из знакомых; коды — «как файл». */
function KindsEditor({ kinds, onChange }: { kinds: string[]; onChange: (k: string[]) => void }) {
  const id = useId();
  const more = KNOWN_KINDS.filter((k) => !kinds.includes(k));
  return (
    <fieldset className="m-0 grid gap-2 border-0 p-0" data-testid="facts-kinds">
      <legend className="mb-1 text-[13px] font-semibold">
        О чём факты канала{' '}
        <span className="font-normal text-muted-foreground">· {kinds.length}</span>
      </legend>
      {kinds.length ? (
        <div className="flex flex-wrap gap-1.5">
          {kinds.map((k) => (
            <span
              key={k}
              data-testid="facts-kind"
              className="inline-flex items-center gap-1 rounded-sm border bg-muted py-0.5 pr-1 pl-2 text-xs"
            >
              {kindText(k)}
              <button
                type="button"
                data-testid="facts-kind-remove"
                aria-label={`Убрать вид «${kindText(k)}»`}
                onClick={() => onChange(kinds.filter((x) => x !== k))}
                className="rounded-sm px-1 text-muted-foreground hover:bg-background hover:text-foreground"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="m-0 text-xs text-muted-foreground">Пока ни одного вида.</p>
      )}
      {more.length ? (
        <label htmlFor={id} className="grid gap-0.5 sm:max-w-xs">
          <Tip content="Вид факта, который рассказывает канал: по видам фабрика выбирает и проверяет факты для роликов">
            <span
              tabIndex={0}
              className="w-max max-w-full text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
            >
              Добавить вид фактов
            </span>
          </Tip>
          <select
            id={id}
            data-testid="facts-kind-add"
            value=""
            onChange={(e) => {
              if (e.target.value) onChange([...kinds, e.target.value]);
            }}
            className={cn(inputBase, 'h-8')}
          >
            <option value="">выберите вид</option>
            {more.map((k) => (
              <option key={k} value={k}>
                {kindText(k)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </fieldset>
  );
}

const ANY_HOST_WORD: Record<string, string> = {
  creator_interview: 'Интервью создателей',
  studio_press: 'Пресс-материалы',
};

/** Источники фактов — ярусы, «с любого сайта» и виды фактов по строкам; прочее — как было. */
function FactSourcesEditor({ channel, doc, sha, onDone }: EditorProps) {
  // Правка начата с этого файла: и sha, и документ — с момента открытия.
  const [base] = useState(sha);
  const [d] = useState(() =>
    doc && typeof doc === 'object' && !Array.isArray(doc) ? (doc as Row) : null,
  );
  const [start] = useState(() => factRowsOf(d));
  const [t1, setT1] = useState<Item[]>(() => itemsOf(start.tier1, OUTLET_FIELDS));
  const [t2, setT2] = useState<Item[]>(() => itemsOf(start.tier2, OUTLET_FIELDS));
  const [any, setAny] = useState<Item[]>(() => itemsOf(start.anyHost, ANY_HOST_FIELDS));
  const [kinds, setKinds] = useState<string[]>(start.kinds);
  const rows = {
    tier1: t1.map((x) => rowOf(x, OUTLET_FIELDS)),
    tier2: t2.map((x) => rowOf(x, OUTLET_FIELDS)),
    anyHost: any.map((x) => rowOf(x, ANY_HOST_FIELDS)),
    kinds,
  };
  const p = factProblems(rows, d);
  const n = nonEmpty(p.tier1) + nonEmpty(p.tier2) + nonEmpty(p.anyHost);
  const why =
    bad(n) ?? (p.doc.length ? 'Поправьте список — план спросим, когда всё в порядке' : null);
  const value = factDoc(d, rows);
  const nameOf = (id: string) => {
    const r = [...rows.tier1, ...rows.tier2].find((x) => x.id === id);
    const h = Array.isArray(r?.hosts) ? (r.hosts as unknown[])[0] : null;
    return typeof h === 'string' && h ? h : 'источник';
  };
  const outletName = (x: Item, i: number) =>
    x.text.hosts?.split(',')[0]?.trim() || `Источник ${i + 1}`;
  const policy = (x: Item) => (
    <span className="text-xs text-muted-foreground" data-testid="facts-ai-policy">
      {aiPolicyText(x.row)}
    </span>
  );
  return (
    <>
      <span className="text-xs text-muted-foreground">
        Проверку сайтов на правила для ИИ-ботов делает фабрика — в записи она остаётся как была.
      </span>
      <RowsEditor
        id="tier1"
        title={tierLabel('1')}
        items={t1}
        fields={OUTLET_FIELDS}
        onChange={setT1}
        problems={p.tier1}
        newRow={newOutlet}
        addLabel="Добавить издание"
        rowName={outletName}
        extra={policy}
      />
      <RowsEditor
        id="tier2"
        title={tierLabel('2')}
        items={t2}
        fields={OUTLET_FIELDS}
        onChange={setT2}
        problems={p.tier2}
        newRow={newOutlet}
        addLabel="Добавить источник"
        rowName={outletName}
        extra={policy}
      />
      <RowsEditor
        id="any-host"
        title="С любого сайта"
        items={any}
        fields={ANY_HOST_FIELDS}
        onChange={setAny}
        problems={p.anyHost}
        newRow={newAnyHost}
        addLabel="Добавить вид источника"
        rowName={(x, i) => ANY_HOST_WORD[x.text.source_type ?? ''] ?? `Вид источника ${i + 1}`}
      />
      <KindsEditor kinds={kinds} onChange={setKinds} />
      {p.doc.length ? (
        <ul
          className="m-0 grid list-disc gap-0.5 pl-5 text-xs text-danger"
          data-testid="facts-doc-problems"
        >
          {p.doc.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : null}
      <RowsWhy kind="fact-sources" why={why} />
      <AsFile kind="fact-sources" value={value} />
      <div>
        <ListWrite
          channel={channel}
          kind="fact-sources"
          value={value}
          base={base}
          why={why}
          say={(line) => factLineText(line, nameOf)}
          onDone={onDone}
        />
      </div>
    </>
  );
}

const channelName = (x: Item, i: number) => x.text.title?.trim() || `Канал ${i + 1}`;
const strOf = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : null);

/** Имя по слову поля: знакомый код — словом, иначе `name` строки, иначе по месту. */
const wordName = (x: Item, words: Record<string, string>, fallback: string) => {
  const t = x.text.id?.trim() ?? '';
  return Object.values(words).includes(t) ? t : (strOf(x.row.name) ?? fallback);
};

/**
 * Происхождение футажа — по строкам (CC-0130): у Reel только официальные каналы (с их каналами
 * на YouTube внутри), у Science/Tech ещё источники футажа и лицензии; прочее — как было.
 */
function FootageOriginEditor({ channel, doc, sha, onDone }: EditorProps) {
  const [base] = useState(sha);
  const [d] = useState(() =>
    doc && typeof doc === 'object' && !Array.isArray(doc) ? (doc as Row) : null,
  );
  const [start] = useState(() => footageRowsOf(d));
  const { science } = start;
  const [acc, setAcc] = useState<Item[]>(() => itemsOf(start.accepted, ACCEPTED_FIELDS));
  const [ref, setRef] = useState<Item[]>(() => itemsOf(start.refused, REFUSED_FIELDS));
  const accepted = acc.map((x) => rowOf(x, ACCEPTED_FIELDS));
  const of = originFields(accepted);
  const [orig, setOrig] = useState<Item[]>(() => itemsOf(start.origins, of));
  const origins = orig.map((x) => withOnScreen(rowOf(x, of)));
  const ofs = officialFields(science, origins);
  const cf = channelFields(science);
  const [off, setOff] = useState<Item[]>(() => itemsOf(start.official, ofs));
  const [chans, setChans] = useState<Record<number, Item[]>>(() =>
    Object.fromEntries(
      off.map((x) => [x.uid, Array.isArray(x.row.channels) ? itemsOf(x.row.channels, cf) : []]),
    ),
  );
  const official = off.map((x) => {
    const r = rowOf(x, ofs);
    const c = chans[x.uid] ?? [];
    return Array.isArray(x.row.channels) || c.length
      ? { ...r, channels: c.map((y) => rowOf(y, cf)) }
      : r;
  });
  const rows = {
    science,
    official,
    origins,
    accepted,
    refused: ref.map((x) => rowOf(x, REFUSED_FIELDS)),
  };
  const p = footageProblems(rows);
  const n =
    nonEmpty(p.official) +
    p.channels.reduce((s, c) => s + nonEmpty(c), 0) +
    nonEmpty(p.origins) +
    nonEmpty(p.accepted) +
    nonEmpty(p.refused);
  const why =
    bad(n) ?? (p.doc.length ? 'Поправьте список — план спросим, когда всё в порядке' : null);
  const value = footageDoc(d, rows);
  const officialName = (pat: string) => {
    const r = official.find((x) => x.pattern === pat);
    return strOf(r?.seen_as)?.split(';')[0]?.trim() || pat;
  };
  const say = (line: string) =>
    footageLineText(line, {
      origin: (id) => originName(origins.find((o) => o.id === id)),
      licence: (id) => licenceName(id, accepted),
      official: officialName,
    });
  const ytChannels = (x: Item) => {
    const i = off.findIndex((y) => y.uid === x.uid);
    return (
      <RowsEditor
        id="yt"
        title="Его каналы на YouTube"
        items={chans[x.uid] ?? []}
        fields={cf}
        onChange={(v) => setChans((m) => ({ ...m, [x.uid]: v }))}
        problems={p.channels[i] ?? []}
        newRow={newChannel}
        addLabel="Добавить канал"
        rowName={channelName}
      />
    );
  };
  return (
    <>
      <span className="text-xs text-muted-foreground">
        {science
          ? 'Откуда канал берёт футаж, под какими лицензиями и как подписывать автора; остальное в файле остаётся как было.'
          : 'Официальные каналы правообладателей: их ролики фабрика узнаёт как официальные; остальное в файле остаётся как было.'}
      </span>
      {science ? (
        <RowsEditor
          id="origins"
          title="Источники футажа"
          items={orig}
          fields={of}
          onChange={setOrig}
          problems={p.origins}
          newRow={newOrigin}
          addLabel="Добавить источник"
          rowName={(x, i) => originName({ who: x.text.who, name: x.row.name }, i)}
          extra={(x) => {
            const t = foundByText(x.row);
            return t ? (
              <span className="text-xs text-muted-foreground" data-testid="footage-found-by">
                {t}
              </span>
            ) : null;
          }}
        />
      ) : null}
      <RowsEditor
        id="official"
        title="Официальные каналы правообладателей"
        items={off}
        fields={ofs}
        onChange={setOff}
        problems={p.official}
        newRow={newOfficial}
        addLabel="Добавить правообладателя"
        rowName={(x, i) =>
          x.text.seen_as?.split(';')[0]?.trim() ||
          x.text.pattern?.trim() ||
          `Правообладатель ${i + 1}`
        }
        extra={ytChannels}
      />
      {science ? (
        <>
          <RowsEditor
            id="accepted"
            title="Лицензии, которые берём"
            items={acc}
            fields={ACCEPTED_FIELDS}
            onChange={setAcc}
            problems={p.accepted}
            newRow={newAccepted}
            addLabel="Добавить лицензию"
            rowName={(x, i) => wordName(x, LICENCE_WORDS, `Лицензия ${i + 1}`)}
          />
          <RowsEditor
            id="refused"
            title="Лицензии, которые не берём"
            items={ref}
            fields={REFUSED_FIELDS}
            onChange={setRef}
            problems={p.refused}
            newRow={newRefused}
            addLabel="Добавить отказ"
            rowName={(x, i) => wordName(x, REFUSED_WORDS, `Отказ ${i + 1}`)}
          />
        </>
      ) : null}
      {p.doc.length ? (
        <ul
          className="m-0 grid list-disc gap-0.5 pl-5 text-xs text-danger"
          data-testid="footage-doc-problems"
        >
          {p.doc.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : null}
      <RowsWhy kind="footage-origin" why={why} />
      <AsFile kind="footage-origin" value={value} />
      <div>
        <ListWrite
          channel={channel}
          kind="footage-origin"
          value={value}
          base={base}
          why={why}
          say={say}
          onDone={onDone}
        />
      </div>
    </>
  );
}

function ListEditor(props: EditorProps) {
  if (props.kind === 'affiliate') return <AffiliateEditor {...props} />;
  if (props.kind === 'fact-sources') return <FactSourcesEditor {...props} />;
  return <FootageOriginEditor {...props} />;
}

/** «Править список…» под чтением списка: раскрыть — правка со свежего файла. */
export function ListEdit({
  channel,
  kind,
  doc,
  sha,
}: {
  channel: string;
  kind: ListKind;
  doc: unknown;
  sha: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<ChannelListWriteResult | null>(null);
  return (
    <div className="grid gap-2" data-testid={`list-${kind}-edit`}>
      {done ? (
        <Done tone="ok" testId="list-done" title="Список записан" onClose={() => setDone(null)}>
          <span>Фабрика записала файл и сохранила его в своей истории.</span>
          <More className="mt-0">
            <span>{done.path}</span>
            {done.commit ? <span>запись фабрики: {done.commit}</span> : null}
          </More>
        </Done>
      ) : null}
      <Disclosure
        id={`list-${kind}`}
        label="Править список…"
        tip="Список канала целиком; фабрика сначала проверит его и покажет план, запишет — после вашего «да»"
        open={open}
        onOpenChange={setOpen}
      >
        <ListEditor
          channel={channel}
          kind={kind}
          doc={doc}
          sha={sha}
          onDone={(r) => {
            setOpen(false);
            setDone(r);
          }}
        />
      </Disclosure>
    </div>
  );
}

function EndingPlanView({ plan }: { plan: EndingRenderPlan }) {
  const missing = plan.needs.filter((n) => n.required && (!n.stored || n.present === false));
  return (
    <>
      <PlanHead plan={plan} yes="можно собрать" no="собрать нельзя" />
      {plan.batches.length ? (
        <p className="m-0" data-testid="ending-plan-batches">
          Идёт батч канала — концовку соберём после него.
        </p>
      ) : null}
      {plan.needs.length ? (
        <div className="grid gap-1" data-testid="ending-plan-needs">
          <span className="text-muted-foreground">Что возьмёт рендер из данных канала:</span>
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {plan.needs.map((n) => (
              <li key={n.key} className={cn(missing.includes(n) && 'text-danger')}>
                {n.what}
                {missing.includes(n) ? ' — нет' : ''}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {plan.ok ? (
        <p className="m-0 text-xs text-muted-foreground">
          Рендер запустится отдельно и займёт около минуты; клип заменит концовку канала.
        </p>
      ) : null}
      <More className="mt-0">
        <span>
          {plan.action} · {plan.channel}
        </span>
        {plan.refusal ? <span>код: {plan.refusal.code}</span> : null}
        {plan.refusal?.details.map((d) => (
          <span key={d}>{d}</span>
        ))}
        {plan.argv ? <span>{plan.argv.join(' ')}</span> : null}
        {plan.batches.map((b) => (
          <span key={b}>батч: {b}</span>
        ))}
        <span>журналы: {plan.log_dir}</span>
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

/** «Собрать концовку…»: только когда фабрика умеет её собрать (`render.available`). */
export function EndingRender({ channel }: { channel: string }) {
  const [done, setDone] = useState<EndingRenderResult | null>(null);
  const after = useAfterChannelListWrite(channel);
  return (
    <div className="grid gap-2" data-testid="ending-render-write">
      {done ? (
        <Done
          tone="ok"
          testId="ending-started"
          title="Рендер концовки запущен"
          onClose={() => setDone(null)}
        >
          <span>Клип появится через минуту-другую — карточка концовки обновится сама.</span>
          <More className="mt-0">
            <span>pid {done.pid}</span>
            <span>журнал: {done.log}</span>
            <span>клип: {done.out}</span>
          </More>
        </Done>
      ) : null}
      <div>
        <WriteAction
          id="ending-render"
          label="Собрать концовку…"
          title="Собрать концовку канала?"
          description="Фабрика проверила, есть ли всё для рендера и не идёт ли батч канала."
          body={{}}
          tip="Фабрика покажет план; рендер запустится после вашего «да»"
          confirmLabel="Собрать"
          pendingLabel="Запускаю…"
          triggerVariant="outline"
          yes
          plan={() => planEnding(channel)}
          act={(c) => renderEnding(channel, c)}
          view={(p) => <EndingPlanView plan={p} />}
          problemText={listProblemText}
          onSettled={after}
          onDone={setDone}
        />
      </div>
    </div>
  );
}
