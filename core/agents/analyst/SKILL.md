---
name: analyst
description: Collect YouTube Analytics metrics (views, engagedViews, average view percentage/duration, likes, subscribers gained) once a day for every live video of every channel in publish/uploads.json, as a daily series per video in analytics/<channel>/daily.jsonl. The base data layer of version 2.1 - CF-0021/0022 and later read it, they do not replace it. Also (CF-0588) the Studio read on hooks: "viewed vs swiped away" of the last videos into analytics/<channel>/studio.jsonl, through agents/analyst/studio_read.py. And (CF-0021) the daily summary: each video's metrics beside its style (acceptance-log profile) per channel in analytics/<channel>/summary/<day>.md + .json, through agents/analyst/summary.py. And (CF-0023) the footage list: agents/analyst/footage_wanted.py collect after every closed batch and once a week - what the written scripts asked for and the footage of every batch of a channel did not give, one row per thing to get, in analytics/<channel>/footage-wanted.md + .json.
---

# Analyst (веха 2.1) — первый кусок: сбор метрик раз в сутки (`CF-0020`)

Этот каталог — агент `analyst` вехи 2.1. Как и Publisher, он живёт **в корневом
репозитории** (`.gitignore` пропускает `agents/analyst/`), отдельного git у него
нет и в `agents.lock.json` он не входит. Своих секретов у него нет: он входит
токеном Publisher (`agents/publisher/.env`, `publisher_auth.analytics_credentials`,
scope `yt-analytics.readonly`, `CF-0589`).

## Команды

```
agents/publisher/.venv/bin/python agents/analyst/metrics.py collect [--channel <канал>] [--day YYYY-MM-DD]
python3 agents/analyst/metrics.py collect --dry-run [--channel <канал>] [--day YYYY-MM-DD]   # какие ролики и какие запросы, без сети
python3 agents/analyst/metrics.py show [--channel <канал>] [--first-days N]                 # окно «первые N дней» (по умолчанию 7) — числа YouTube из windows.jsonl
```

Живой сбор — только через `agents/publisher/.venv/bin/python`: Google-библиотеки
стоят там. Системный `python3` годится для `--dry-run` и `show`.

Коды выхода `collect`: **0** — собрано (пропущенные ролики названы в выводе и в
журнале прогонов); **2** — ошибка настройки (`.env`, нет библиотек); **3** —
пользователь переразрешает: нет токена, нет scope `yt-analytics.readonly`, токен
истёк или отозван (`invalid_grant`) — строка называет команду
`agents/publisher/.venv/bin/python agents/publisher/upload.py --authorize`;
**4** — API не ответил после повторов с паузами (квота, 5xx) или отверг сам
запрос; собранное до сбоя сохранено, повторный `collect` догонит. 403 квоты
(`quotaExceeded`, `dailyLimitExceeded`, ...) — это тоже ошибка прогона, не ролика:
повторы с паузами, потом код 4; **5** (`CF-0623`) — API отказало всему прогону,
а не ролику: YouTube Analytics API выключено в проекте Google Cloud токена (403
`accessNotConfigured` / `SERVICE_DISABLED`, «has not been used in project … or it
is disabled» — сбор останавливается на первом же ответе, в строке прогона
`outcome: api-disabled` и `activation_url` из ответа) или каналу отказали **все**
спрошенные ролики (`outcome: all-forbidden` — токен не того канала?; другие
каналы собираются). В обоих случаях — вопрос в журнале вопросов (`shared/needs_you.py`, `CF-0652`;
`--needs-you-dir`, иначе `NEEDS_YOU_DIR`, иначе `<корень>/needs-you`; один живой на
причину — ключ `analytics-api-disabled` / `analytics-all-forbidden:<канал>`) и
уведомление шины `shared/notify.py` вида `needs_human` (Telegram, если включён; ключ
— причина и тихоокеанский день, одно в сутки). Любой другой 403 — пропуск ролика
`forbidden`.

Политика YouTube API (`CF-0618`, `agents/publisher/api_data.py`): живой `collect`
сначала запускает удаление API Data по сроку (через 25 дней после первого
`invalid_grant` без нового согласия — `daily.jsonl`, `windows.jsonl`, `runs.jsonl`, `summary/` и
API-строки журнала; Studio-чтения не трогаются), а после сбора обновляет API-строки
журнала через `videos.list` раз в 7 дней. Ни то, ни другое сбор не останавливает. То же
удаление идёт в каждом тике `shared/batch_schedule.py` — при отозванном токене оператор
`collect` не запускает, срок держит тик. Удалить по просьбе владельца —
`python3 agents/publisher/api_data.py purge --all` (сухой прогон) → `--delete`.

## Когда запускается

Раз в сутки. До оркестратора 2.2 — **оператор в начале сессии** (или после
батча): `publisher_auth.py status` → если 0/1, `metrics.py collect`, **затем**
`python3 agents/analyst/summary.py daily` (сводка дня, раздел «Сводка дня» ниже;
запускается и при коде 3/4/5 сбора — сводит то, что уже есть). Код 3 —
строка пользователю «переразрешить», батч от этого не стоит. Расписание
(launchd/оркестратор) — веха 2.2. Там же, в начале сессии, — страховка чтения Studio:
`python3 agents/analyst/studio_read.py due`; код 1 — визит в Studio по разделу «Чтение
Studio (`CF-0588`)» ниже (только если пользователь в этой сессии разрешил Studio; нет —
одна строка пользователю «пора прочитать Studio: <каналы>»). Пропущенный день не теряется: следующий сбор
спрашивает с первого неокончательного дня каждого ролика.

**Список футажа «что добыть»** (`CF-0023`, раздел ниже) — не раз в сутки, а по событию:
после закрытия каждого батча канала (стадия `footage-wanted` в плане канала; где она
стоит — `python3 shared/run_plan.py show <канал>`) —
`python3 agents/analyst/footage_wanted.py collect --channel <канал>`, и **раз в неделю**
(в начале первой сессии недели) — `collect` без `--channel` по всем каналам, с
подключённым Archive, чтобы прочитать и упакованные батчи.

## Что спрашивается

Для каждого ролика из `publish/uploads.json` (читается только через
`agents/publisher/upload_records.py`) — без `removed_at` и с `publish_at` в
прошлом (строки переноса без `publish_at` — по `publish_day`). Два запроса
`reports.query` на ролик, `ids=channel==MINE`, `dimensions=day`,
`filters=video==<id>`, `sort=day`, с первого неокончательного дня по `--day`
(по умолчанию — вчера по тихоокеанскому времени: YouTube Analytics считает дни
в America/Los_Angeles):

| группа | метрики |
|---|---|
| core | `views`, `likes`, `subscribersGained`, `averageViewDuration`, `averageViewPercentage` |
| engaged | `engagedViews` |

Раздельно — потому что совместимость `engagedViews` (метрика 2025 года) с
остальными в одном отчёте не подтверждена документацией; отказ (400) на ней
стоит одной колонки (`null`, причина в журнале прогонов), а не всего сбора.

**Сравнивать ролики — по `engagedViews`**: с 2025-03-31 `views` у Shorts
считается с первого кадра, без минимального времени.
«Досмотрели / пролистали» в API нет — это `CF-0588` (чтение Studio, раздел ниже).

## Где данные и в каком виде

`analytics/<канал>/daily.jsonl` — строка на (ролик, день), единственный
писатель и читатель — `metrics_store.py`:

```json
{"channel": "example-film", "video_id": "VV-UM01wb5c", "entry_id": "rebuilds/2026-09-27T1757Z/backrooms", "day": "2026-09-27", "age": 0, "views": 120, "engagedViews": 81, "averageViewPercentage": 63.2, "averageViewDuration": 21, "likes": 4, "subscribersGained": 1, "final": true, "collected_at": "2026-10-06T09:00:00Z"}
```

* дневной ряд, а не накопительный снимок: из него кривые и `final`; окно из
  дневных строк **не собирается** — ни суммы, ни средние (`CF-0624`, политика
  YouTube API III.E.4.h(i));
* `final: false` — день моложе `FINAL_LAG_DAYS` (3) от дня съёма: Analytics
  догоняет 2–3 дня; такую строку следующий сбор заменит; окончательные дни
  повторно не спрашиваются;
* повторный съём того же дня — замена по ключу (ролик, день), не дубль; файл
  переписывается целиком через временный и `rename`;
* `entry_id` — ключ к приёмке (`publish/acceptance-log.json`) и к батчу;
* `analytics/<канал>/windows.jsonl` (`CF-0624`) — строка на (ролик, окно):
  числа YouTube за окно целиком — `reports.query` за `startDate..endDate` **без
  `dimensions`** (обе группы метрик), средние считает YouTube. Окна —
  `metrics_store.WINDOW_DAYS` (сейчас первые 7 дней: их читают `summary.py` и
  `metrics.py show`); `start` — день публикации (PT), `end` — `start + N − 1`,
  но не позже `--day` сбора (вчера PT, как у дневных строк; молодой ролик —
  `complete: false`). `final` — окно полное и его последний день старше 3 дней;
  неокончательное окно следующий `collect` спрашивает снова и заменяет,
  окончательное — больше никогда. Ролик, собранный до `CF-0624`, получает своё окно
  одним запросом при первом сборе после него. Нет строки окна — читатели пишут «нет
  окна YouTube», из дневных строк не пересчитывают. Квота: 2 запроса на ролик за
  дневной ряд + 2 на каждое открытое окно (ролики первых ~10 дней);
  `collect --dry-run` печатает число запросов;
* `analytics/<канал>/runs.jsonl` — строка на прогон: когда, до какого дня, кого
  спросили, кого пропустили и почему (`removed`, `not-yet-published`,
  `no-data-yet`, `up-to-date`, `forbidden`), какие метрики недоступны, исход
  (`outcome`: `ok`, `nothing-to-ask`, `reauthorize`, `api-error`, `api-disabled`
  с `activation_url`, `all-forbidden` — `CF-0623`).

Поканально: каждый канал — свой каталог; канал берётся из строки журнала, не
из кода. Пока токен один (канал `PUBLISHER_CHANNEL_ID`), ролик чужого канала
API отвергнет — он будет пропущен с пометкой `forbidden`, не записан чужим.

## Карта модулей

| модуль | что делает |
|---|---|
| `metrics.py` | план (какие ролики, с какого дня), сбор, CLI `collect`/`show`, коды выхода |
| `metrics_store.py` | `analytics/<канал>/daily.jsonl`, `windows.jsonl` (окна YouTube, `CF-0624`) и `runs.jsonl`: чтение, слияние, `final`, окна |
| `analytics_client.py` | единственный вызов Google (`reports.query`), разбор ответа, классификация ошибок, повторы с паузами |
| `studio_read.py` | чтение Studio (`CF-0588`): `plan` (какие ролики читать), `parse`/`record` (проверка и разбор прочитанного, запись), `due` (пора ли читать) |
| `studio_center.py` | чтение Studio по действиям пользователя в центре (`CF-0735`): `studio_read_due` (хуки `batch-start`/`upload`/`center-first-open-of-day`), `studio_read_launch` (кнопка «Прочитать Studio»: план/подтверждение, отдельный процесс `claude -p --chrome` с логом), `studio_read_result` (итог строкой), `commit_read_data` / `commit-read` (коммит данных чтения, `CF-0786`), `studio_insurance_notify` (страховка раз в сутки), `scheduled_read` (плановое чтение из тика расписания, `CF-0926`) |
| `summary.py` | сводка дня (`CF-0021`): ролик → `entry_id` → `profile` строки приёмки → окно API и чтение Studio; таблица по роликам и агрегаты по измерениям стиля |
| `footage_wanted.py` | список футажа «что добыть» (`CF-0023`): `collect [--channel] [--since]` — незакрытые потребности сценариев всех батчей канала (в т.ч. упакованных в zip) → `analytics/<канал>/footage-wanted.md` + `.json` |

Тесты — `tests/test_analyst_metrics.py`, `tests/test_analyst_studio_read.py`, `tests/test_studio_center.py`, `tests/test_studio_read_commit.py`, `tests/test_analyst_summary.py`, `tests/test_footage_wanted.py` (корень), Google подставной, настоящий
`publish/` не читается.

## Чтение Studio (`CF-0588`)

Гриль 06.10 (Q5, Q5′): главной метрики Shorts — «досмотрели / пролистали» — в API нет,
только в Studio. Отдельных визитов почти не
делать: оркестратор читает Studio через Claude in Chrome **заодно** с тем, что уже делает
там. Скрипт `agents/analyst/studio_read.py` **в Studio не ходит** — он говорит, что читать,
проверяет и разбирает прочитанное и пишет его.

**Разрешения.** Любое действие в Studio — только в сессии, где пользователь разрешил
работу в Studio (написал «загрузил X», поручил батч или прямо сказал «прочитай Studio»).
Чтение — **без единого клика «Изменить» / «Оспорить» / «Удалить» / «Принять»**: только
открыть страницу, переключить вкладку или период, прочитать. Кнопки действий по
заявкам и ограничениям — не нажимать никогда, а сказать пользователю.

### Когда (три хука, одна проверка)

| хук | где встроен | команда перед визитом |
|---|---|---|
| 1. после «загрузил X» | `agents/publisher/SKILL.md`, «Путь через Studio», шаг 9 — тем же визитом | `studio_read.py due --channel <канал> --hook upload` |
| 2. перед стартом батча канала | `docs/running-a-batch.md`, «Before `batch-start`: the Studio read» | `studio_read.py due --channel <канал> --hook batch-start` |
| 3′. первое открытие центра за день (`CF-0735`) | командный центр зовёт `studio_center.studio_read_due(None, "center-first-open-of-day")` | то же правило, что у хуков; повторное открытие в тот же день — правило страховки |
| 3″. плановое чтение (`CF-0926`) | тик `shared/batch_schedule.py` раз в сутки в `studio_read_at` (08:15 МСК) — `studio_center.scheduled_read` | `studio_read_due(None, "schedule")` — правило хука (`hook_min_gap_hours`) |
| 3. страховка раз в сутки | до расписания 2.2 — **оператор в начале сессии**, рядом со сбором метрик; с `CF-0926` — только если плановое чтение не вышло | `studio_read.py due` (все каналы) |

`due` — код **1** и строка `due <канал>: пора читать (...)` — читать; код **0** и
`ok <канал>: ...` — не надо; **2** — ошибка (нет настроек канала). Хук не перечитывает,
если полное чтение было моложе `hook_min_gap_hours` (два хука подряд — один визит);
страховка — если полное чтение старше `insurance_hours`. 

Настройки — поканально, `channels/<канал>.json` → `analyst.studio_read`:
`last_videos` (N — сколько последних опубликованных роликов читать), `insurance_hours`,
`hook_min_gap_hours`. Канал без этого блока `due` называет строкой `skip` и не читает.

### Кнопка в центре и страховка (`CF-0735`)

Читает Studio сессия Claude, которая ведёт Chrome пользователя (Claude in Chrome).
Запускать `claude -p --chrome` без присмотра документация Claude Code не описывает,
поэтому чтение начинается с **кнопки «Прочитать Studio» в командном центре**: клик —
значит пользователь у ноутбука и Chrome открыт. `agents/analyst/studio_center.py`:

* `studio_read_due(channel|None, hook, root, now)` → `{due, why, last_read_at, age_hours,
  hooks, first_open_today, running, channels, skipped}` — правило `studio_read.due`;
  `center-first-open-of-day` пишет первое открытие дня (МСК) в
  `schedule/studio-read/center-opens.json` (атомарно, под блокировкой);
* `studio_read_launch(by, via, confirmed=False)` — без подтверждения план (ничего не
  запущено), с ним — отдельный процесс (своя сессия ОС, промпт на stdin, вывод в
  `schedule/studio-read/runs/<run_id>.log`, cwd — корень фабрики): `claude -p --chrome
  --permission-mode dontAsk --allowedTools <правило> <правило> … --add-dir <корень>`, каждое
  правило отдельным аргументом: `mcp__claude-in-chrome__*`, `Bash(python3
  agents/analyst/studio_read.py plan:*)` / `parse:*` / `record:*`, `Bash(date -u +%Y-%m-%dT%H:%M:%SZ)`, `Read`,
  `Write` — с промптом «шаги 1–7 этого раздела, только studio.youtube.com, только чтение»,
  где названы ровно эти командные строки (`studio_center.read_commands`): по одному каналу
  и одной команде за вызов, без циклов, `;`/`&&`/`cd`, абсолютных путей и `.venv`
  (`CF-0759`: первый запуск 15.10 отказан — модель обернула `plan` в `for c in …; do …
  $c; done`, такая форма не совпадает ни с одним правилом, а `dontAsk` превращает
  вопрос в отказ); прочих скриптов эта сессия не запускает, git тоже не трогает. **Коммит данных чтения — фабрика** (`CF-0786`): сессия идёт
  под бегуном `studio_center.py session <запись запуска>` (его pid — `pid` запуска, его
  группа держит сессию), и когда сессия кончилась, бегун зовёт `commit_read_data` — один
  коммит ровно тех файлов чтения, что git видит изменёнными или новыми
  (`analytics/<канал>/studio.jsonl`, `studio_visits.jsonl`; общий коммиттер `shared/runlog/git_commit.write_and_commit`,
  никакого `git add -A`). Под батчем, прошедшим `batch-start`, — не коммитит (`deferred`:
  коммит analytics/ под прогоном — `code_drift`), оставленное коммитит шаг `commit-read`
  следующего батча. Итог — строка `STUDIO_READ_COMMIT: <статус> - …`
  в журнале запуска и `commit` записи запуска; без неё грязный analytics/ уронил бы
  следующий `batch-start` (`CF-0479`: analytics/ для него — код, не запись). Отказы: `bad_who`, `no_channels`, `running` (чтение уже
  идёт), `no_claude`, `spawn_failed`. Первый настоящий запуск был при пользователе (его
  «да» 13.10); с 09.11 чтение идёт и само по расписанию (`CF-0926`, ниже); тесты
  подставляют `claude` (`STUDIO_READ_CLAUDE`). Закрытые каналы (расписание выключено —
  ExampleScience с 05.11) кнопка не читает (`readable_channels`, `CF-0926`);
* `studio_read_result(run_id|лог)` → код итога: `read` (прочитано — и только если визит
  действительно записан через `via` после старта), `no_extension` (расширение не
  подключено), `login_needed` (нужен вход в Google), `error`, `running`. Сессия кончает
  ответ строкой `STUDIO_READ_RESULT: <код> - <строка>`; без неё код выводится из журнала;
  пока бегун коммитит — `running`; потом `commit` (что сделал коммит, `CF-0786`), а его
  строка (закоммичено / отложено под батчем / отказ) дописана к `line`;
* страховка — `studio_insurance_notify`: одно `needs_human` по-русски «📊 Studio не читали
  N часов (Reel, Tech) — статистика роликов не обновляется. / Плановое чтение: <что вышло>. /
  Нужно от вас: <что>» (`CF-0925`/`CF-0926`; каналы вне расписания — закрытые — не
  считаются; молчит, пока плановое чтение дня впереди или идёт и после удачного —
  `scheduled_insurance_gate`) со ссылкой на центр
  `http://127.0.0.1:8790/` (главная), не чаще раза в сутки на фабрику (`schedule/studio-read/insurance.json`);
  зовётся каждым тиком `shared/batch_schedule.py` и вторым шагом стадии `studio-read-due`.
  Пропуск чтения перед батчем (`studio-read`, `notify: quiet`) — тихая строка журнала
  батча, не уведомление.

### Плановое чтение по расписанию (`CF-0926`)

Решение пользователя 09.11: «чтение studio запускал сам по расписанию, как и
батчи+публикацию». Тик `shared/batch_schedule.py` (каждые 15 мин) зовёт
`studio_center.scheduled_read`:

* раз в московские сутки, не раньше `studio_read_at` (по умолчанию 08:15; `batch_schedule.py
  settings --studio-read-at HH:MM --by <кто>`, выключатель `--studio-read off|on`) —
  `studio_read_launch(by="schedule", via="tick", confirmed=True)` для активных каналов, которым
  пора (`studio_read_due(None, "schedule")`); в прочитанном JSON `hook` = `"daily"`, запись
  `record --by schedule --via tick`;
* не запускает при открытом батче (`runlog batch-active`), в часе до окна батча любого
  канала (остывание), пока идёт другое чтение; после неудачи — через 30 мин (через 60, если
  нужен вход или расширение), не больше 3 попыток в сутки; состояние —
  `schedule/studio-read/scheduled.json`, запуски — в общей истории `runs/`;
* следующий тик после конца запуска забирает итог и шлёт одно сообщение на запуск:
  «📊 Studio прочитана: Reel — 10 роликов, Tech — 10» (вид
  `studio_read`), при `login_needed` / `no_extension` —
  `needs_human` «⚠️ Studio не прочитана (…): … Нужно от вас: …»; `error` никого не зовёт
  (следующая попытка, а после третьей — страховка). Данные коммитит раннер, как у кнопки.

Сессия планового запуска знает, что пользователя у ноутбука может не быть: Chrome без
расширения — итог `no_extension` сразу, без ожидания. Подробности — `docs/batch-schedule.md`,
«Плановое чтение Studio».

### Что читать (порядок визита)

1. `python3 agents/analyst/studio_read.py plan --channel <канал>` — последние N
   опубликованных живых роликов (по `publish/uploads.json`, без `removed_at`, слот уже
   прошёл), новые сверху, со ссылкой аналитики ролика
   `https://studio.youtube.com/video/<id>/analytics/tab-overview/period-default`.
2. **Убедиться, что Studio показывает этот канал** (аватар / название канала вверху;
   у аккаунта несколько каналов — переключатель «Сменить аккаунт»). Чужой
   канал скрипт отвергнет сам, если узнает ролик из журнала, но новый ролик он не узнает.
3. Для каждого ролика плана: открыть ссылку (Аналитика ролика → вкладка **«Обзор»**)
   и найти долю досмотревших. **С 10.2026 (CF-0639) она здесь:** блок **«Интерес к
   контенту • С момента публикации»**, подпись **«Продолжили смотреть»** (англ. **«Stayed
   to watch»**) и число под ней, например `["Продолжили смотреть", "52,1 %"]`.
   «Пролистали» Studio там **не показывает** — это нормально: `swiped` не передавать и
   не считать как 100 − доля, скрипт оставит `swiped_pct = null` без предупреждения.
   Встречается и карточка **«Реакция зрителей»**: сначала числа, потом подписи
   (`"62,0 %", "38,0 %", "Продолжили смотреть", "Не стали смотреть"`) — тогда числа
   **обязательно** дать полями `viewed` / `swiped` (`"62,0 %"` / `"38,0 %"`), из строк
   такого порядка скрипт их не берёт. Старая карточка **«Досмотрели / Пролистали»**
   (англ. «Viewed vs. swiped away») тоже узнаётся, если вернётся. Текст блока —
   строками **как на странице** в `lines` (`innerText` блока), период из переключателя
   периода — в `period_text` (по умолчанию «С момента публикации» / «Since published»).
   Распознанные числа можно дать полями `viewed` / `swiped` — скрипт сверит их со
   строками.
   **Новый ролик** (меньше суток, ~200 просмотров) блока не имеет, а в «Удержание
   аудитории» написано **«Статистика пока недоступна: недостаточно данных.»** — это
   **нормальное состояние, не ошибка**: ролик всё равно в `videos`, эти строки — в
   `lines`, без чисел. Скрипт запишет обе доли `null` с пометкой `note` (строка
   `NOTE <id>: not enough data yet …`, в визите — `metrics_not_ready`), без `WARN`;
   прочитать ролик в следующий визит. Любая другая страница без доли («Произошла
   ошибка», блок не найден) — `null` с `WARN viewed: not recognised` (в визите —
   `metrics_unrecognised`).
4. Сложить в `scratchpad/studio-read-<канал>-<ГГГГММДДTЧЧММ>.json`:

```json
{"channel": "example-film", "read_at": "2026-10-06T13:15:00+03:00", "hook": "upload",
 "videos": [{"video_id": "ZyXwVuTsRqP", "title": "Example Short A",
             "period_text": "С момента публикации",
             "lines": ["Продолжили смотреть", "52,1 %"]},
            {"video_id": "AbCdEfGhIjK", "title": "Example Short B",
             "period_text": "С момента публикации",
             "lines": ["Удержание аудитории", "Статистика пока недоступна: недостаточно данных."]}]}
```

   `read_at` — время чтения со смещением; `hook` — `upload` | `batch-start` | `daily` |
   `manual`; `video_id` или `url` ролика (id из ссылки).
5. `python3 agents/analyst/studio_read.py parse <json> --channel <канал>` — посмотреть
   разбор и строки `WARN` (ничего не пишет); затем
   `python3 agents/analyst/studio_read.py record <json> --channel <канал>`.
   Код **2** — отказ, ничего не записано (нет `read_at` с поясом, не тот канал, ролик
   чужого канала по журналу); поправить прочитанное, не вывод.
   Кто записал (`CF-0692`, необязательно): `record ... --by user --via center` или из
   Python `studio_read.record(parsed, root, now, by="user", via="center")` — командный
   центр зовёт `parse_read` для плана (ничего не пишет), а после подтверждения
   пользователя — `record(..., by="user", via="center")`. `by`/`via` — короткие
   (≤ 40 знаков) непустые строки в одну строку, иначе отказ до любой записи. Без них
   записи ровно как раньше.
6. **Последним** — `python3 agents/analyst/studio_center.py commit-read` (коммит данных
   чтения, `CF-0786`: иначе грязный `analytics/` уронит следующий `batch-start`). `WARN` — нераспознанное: оставить как есть (сырые строки сохранены), не
   дописывать числа из головы; повторяющийся `WARN` на живом чтении — задача на
   разбор (поправить метки в `studio_read.py`).

### Что пишется

* `analytics/<канал>/studio.jsonl` — `metrics_store.py`: строка `kind: "studio"` на
  (ролик, `read_at`): `viewed_pct`, `swiped_pct` (может быть `null` — Studio его не
  показывает, CF-0639), `period_text`, `raw_lines`, `warnings`, `note` (только у ролика с
  «недостаточно данных»), `hook`, `recorded_at`; `recorded_by` и `via` (`CF-0692`) —
  только если `record` их получил (без них строка байт-в-байт прежняя; повтор того же
  чтения, отличающийся лишь ими или `recorded_at`, — «без изменений»). **Отдельно от `daily.jsonl`** (API-дневной ряд): это доля за
  период страницы, снимок своего времени, а не день. Повтор того же чтения — замена,
  не дубль; последнее чтение ролика — `metrics_store.latest_studio()`.
* `analytics/<канал>/studio_visits.jsonl` — строка на визит: когда, хук, сколько роликов,
  какие без чисел, ролики без id (с их строками); `recorded_by` / `via` — только если заданы. Его читает `due`.


## Список футажа «что добыть» (`CF-0023`)

Что реально требовалось написанному сценарию и не нашлось в футаже — по **всем** батчам
канала, одной таблицей: какой футаж стоит добыть следующим.

```
python3 agents/analyst/footage_wanted.py collect [--channel <канал>] [--since YYYY-MM-DD]
        [--archive DIR | --no-archive] [--out DIR] [--print] [--no-write]
```

**Когда.** После закрытия каждого батча канала (стадия `footage-wanted` плана канала,
эта команда с `--channel` батча; порядок закрытия — `python3 shared/run_plan.py show <канал>`) и раз в неделю по всем каналам (раздел «Когда
запускается»). Каналы — `channels/*.json` и папки `pipeline/<канал>/`, не код; батчи
канала — `pipeline/<канал>/<батч>/` и пересборки `pipeline/rebuilds/<батч>/` с его
`channel`. `--out DIR` пишет в `DIR/<канал>/` (пробный прогон мимо `analytics/`).
Выход **0** — записано; **2** — неизвестный канал, кривой `--since`, нет корня.

**Что считается незакрытой потребностью** — только записанное стадиями батча:

| код | стадия | запись |
|---|---|---|
| `anchor_no_picture` | монтаж | `05` `videos[].unresolved_anchors`: ни один кадр не прошёл порог |
| `anchor_short` | монтаж | там же: кадров хватило не на весь блок («cover only») |
| `frame_contradicts` | судья кадров | `06` `verdicts[]`: диктор называет то, чего нет в кадре |
| `frame_foreign` | судья кадров | `06` `verdicts[]`: блок закрыт чужим кадром |
| `visual_claim_uncovered` | сценарий | `03` `warnings[]`: строка указывает на кадр, которого нет (`claims[].anchors[]` со `status: absent`) |
| `pool_too_thin`, `no_second_source` | сценарий / монтаж | `03` `warnings[]` и `skipped[]`, `05` `refusals[]` |
| `event_footage_short` | сценарий | `03` `warnings[]` (`CF-0575`) |
| `no_source` | охотник | `01` `skipped_topics[]` |

`03` `warnings[]` — состояние пула **после** шага добора (`CF-0345`), так что
закрытое добором не считается. Рядом читаются исход шага для темы
(`work/supplement-step.json`: `sources`, `wall_ceiling`, `nothing_to_try`) и запрос
(`work/supplement-requests/[consumed/]<тема>.json`): его `entities` — что искали, его
`candidates` — ролики, которые охотник уже нашёл. `thin_scene` (сценарий не набрал
моментов) — не нехватка футажа и не считается.

**Строка = одна вещь, которую добыть**, по видам: **работа** (потребность темы целиком —
`title_ref` темы), **персона** (якорь называет человека — `supplement.anchors[].entities`
проверки покрытия; или тема-персона), **событие** (`event_footage_short` — сущность
`scene` запроса), **сцена** (кадр якоря без названной персоны — сцены работы темы, с
примерами фраз). Имена сравниваются без регистра, диакритики и пунктуации; одно имя из
разных батчей — одна строка со счётчиками: `тем` (разные `topic_id` — пересборка той же
темы не вторая), `батчей`, `промахов` (записей стадий). Порядок: больше тем → свежее
→ больше промахов → имя. Потребность темы, которую не называет ни одна запись `01`/`03`
и ни один запрос, — строка в заметках, не угаданная строка списка.

**Где добыть — только то, что фабрика уже знает:** кандидаты запросов добора (id,
название, канал, `official`/нет; «уже в пуле», если id есть в индексе) и официальные
каналы `agents/*/config/footage_origin.json`, чей `pattern`/`owners` есть в `network` /
`rights_holder` работы (у персоны и сцены — работы её темы). Нет ни того ни другого —
«—», ничего не придумывается. **В пуле сейчас** — записи `shared/footage/index.json`
(только чтение), где имя стоит в названии или заметке целым набором слов; пул временный
(`CF-0358`), так что это «сейчас», не «навсегда».

**Упакованные батчи.** Батч старше 30 дней уходит в zip на Archive (`scripts/monthly_archive.py`:
`/Volumes/Archive/shorts-content-factory-pipeline/<группа>/<YYYY-MM>.zip`, члены
`<батч>/<путь>`). Сборщик читает нужные JSON прямо из zip, ничего не распаковывая; батч,
который есть и на диске, и в zip, читается один раз (с диска). Нет папки (Archive не
подключён, ещё ничего не упаковано) или битый zip — строка в заметках, не ошибка.

**Куда.** `analytics/<канал>/footage-wanted.md` (людям: таблица на вид, коды причин) и
`.json` рядом (машине: строки со счётчиками, `reasons`, `examples`, `searched`,
`supplement_outcomes`, `in_pool_now`, `where`, `topic_ids`/`batch_ids`). Оба
переписываются целиком; при тех же данных и `--now` — те же байты. Коммитятся вместе с
`analytics/`. Последняя строка вывода — `TOTAL channel=… batches=… packed=… needs=…
rows=… work=… person=… event=… scene=…`.

## Сводка дня (`CF-0021`)

```
python3 agents/analyst/summary.py daily [--channel <канал>] [--day YYYY-MM-DD] [--first-days N] [--print] [--no-write]
python3 agents/analyst/summary.py join  [--channel <канал>]     # сколько роликов журнала соединились с профилем и метриками
```

**Когда.** Сразу после `metrics.py collect` (раздел «Когда запускается»), каждый день,
по всем каналам журнала (`--channel` — один); канал берётся из `publish/uploads.json`,
не из кода. День по умолчанию — вчера по тихоокеанскому (последний день, который
спрашивает `collect`). Окно API по умолчанию — первые 7 дней ролика.

**Соединение.** `publish/uploads.json` (`video_id` → `entry_id`) → строка
`publish/acceptance-log.json` (по `acceptance.row_keys`) → её `profile` (`CF-0440`) →
`analytics/<канал>/windows.jsonl` (окно «первые N дней» — строка YouTube, `metrics_store.window()`, `CF-0624`) и
`studio.jsonl` (последнее чтение ≤ дня). Ролик журнала не теряется никогда: без
строки приёмки / без `profile` / без строк API / без чтения Studio — пометка в его
строке и строка в разделе «Пробелы»; стиль такого ролика — `unknown`.

**Стиль — один источник на поле:** `profile.pattern`, `profile.rhythm`,
`profile.hook_opener`, `profile.fact_kind`, `profile.tier`. Реестр ротации и
`05-video-editor.json` для них не читаются (в реестре — только pattern/rhythm как их
*назначила* ротация и не на каждый ролик; `05` уходит с диска вместе с батчем).
Пустое поле профиля (ролики до hook openers и оценок) — `unknown`, не дописывается;
дополнить профиль — только `runlog profile --fill`.

**Метрики.** Окно API — числа YouTube за окно целиком (строка `windows.jsonl`):
`engagedViews` (по нему сравнивать), `averageViewPercentage` (и `averageViewDuration` в
`.json`). Нет строки окна (собрано до `CF-0624`, окно ещё не спрошено, N не из
`WINDOW_DAYS`, окно снято позже дня сводки) — `нет метрик API` с причиной в «Пробелах»,
никакого пересчёта из дневных строк.
Studio: «досмотрели %» — доля за период страницы на момент чтения, рядом период и дата
чтения; это не окно N дней. Пометки строки: `не оконч.` — в окне есть неокончательный
день (`final: false`, данные ещё догоняются); `окно < N д` — ролик моложе N дней;
`ещё не вышел`, `снят`, `нет профиля`, `нет метрик API`, `нет чтения Studio`.

**Агрегаты** — помечены «посчитано фабрикой» (`computed_by: factory`, `CF-0624`): это
статистики фабрики по числам YouTube роликов одного владельца (III.E.2.a), стоят рядом с
исходными числами YouTube по роликам (таблица «Ролики»), не вместо них. По каждому
измерению стиля и каждому его значению: роликов; по каждой
метрике n / медиана / среднее / мин–макс / σ; сколько неокончательных и неполных окон;
«выборка мала (<20)», если у какой-то метрики n < 20. Значения идут по имени, не по
метрике. **Выводов сводка не делает** — решение «данные победили вкус» — отдельная
точка при 20–30 роликах на стиль (гриль 06.10); до неё пользователю не говорить «стиль X
лучше» по сводке.

**Куда.** `analytics/<канал>/summary/<день>.md` (людям) и `<день>.json` рядом (машине:
центр читает её через `shared/factory_state.py`, строка метрик канала). Оба переписываются целиком; повторный запуск того же дня на
тех же данных даёт те же байты. Коммитятся вместе с `analytics/` как данные фабрики.
