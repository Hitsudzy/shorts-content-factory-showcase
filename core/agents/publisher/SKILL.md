---
name: publisher
description: Upload an accepted video from publish/ to the channel through the YouTube Data API (videos.insert, OAuth installed-app, resumable), private with a scheduled publishAt, only after an explicit "да" typed by the user at the terminal. Stub of the 2.0 Publisher agent - CF-0016/0017/0018/0019 extend this directory, they do not replace it.
---

# Publisher (веха 2.0) — заглушка, первый рабочий кусок: загрузчик (`CF-0421`)

Этот каталог — агент `publisher` вехи 2.0, а не отдельный путь рядом с ним.
В отличие от остальных агентов, он живёт **в корневом репозитории** (`.gitignore`
пропускает только `agents/publisher/`). Секреты — никогда: client secret и
токен лежат вне любого git-дерева, пути к ним — в `agents/publisher/.env`
(gitignored, образец — `.env.example`).

## Что есть сейчас

```
python3 agents/publisher/publish_card.py build pipeline/<канал>/<батч> <slug>          # карточка при приёмке (CF-0017)
python3 agents/publisher/publish_card.py place pipeline/<канал>/<батч> <slug>          # после «принят»: карточка + ближайший свободный слот (CF-0587)
python3 agents/publisher/publish_queue.py show|next [--channel <канал>]                  # очередь канала: занятые дни, ближайший свободный
python3 agents/publisher/publish_queue.py tomorrow --notify                            # строка оркестратору: пуст ли завтрашний слот (3 — канал на паузе); пустой — и уведомление (CF-0591)
python3 agents/publisher/publish_move.py --channel <канал> [--unplace SLUG]... [--withdraw SLUG]... [--move [БАТЧ/]SLUG=YYYY-MM-DD]... [--apply --by WHO --via WHAT]  # перенос размещённого / снятие в копилку (CF-0856), снятие залитого в запас (CF-0918), сухой прогон без --apply
python3 agents/publisher/channel_pause.py set --channel <канал> --by user --reason "…" [--until YYYY-MM-DD]  # пауза публикаций канала (CF-0569)
python3 agents/publisher/channel_pause.py clear --channel <канал> --by user [--note "…"]                     # снять паузу (запись остаётся)
python3 agents/publisher/channel_pause.py show [--channel <канал>] [--history]                              # кто на паузе (3 — есть пауза)
python3 agents/publisher/publish_window.py check [--channel <канал>]                    # окно паттернов: лента с парами, повторы внутри K (CF-0042)
python3 agents/publisher/publish_window.py record [--channel <канал>] [--dry-run]       # колонки публикации реестра ротации из uploads.json
python3 agents/publisher/note_claims.py publish/<канал>/<YYYY-MM-DD>/<slug>.md --write # утверждения названия/описания (CF-0555)
python3 agents/publisher/studio_fields.py prepare publish/<канал>/<YYYY-MM-DD>/<slug>.md --uploaded  # Studio-путь (CF-0018): JSON полей формы из готовой карточки; --uploaded - файл уже в Studio, «загрузите» не слать (CF-0857)
python3 agents/publisher/studio_fields.py verify <slug|заметка> --read <прочитанное.json>  # сверка того, что показывает Studio, с карточкой (1 — расхождения)
python3 agents/publisher/studio_fields.py record <slug|заметка> --video-id <id> --read <прочитанное.json>  # строка журнала + реестр
python3 agents/publisher/studio_fields.py edited --slug <slug> --note "что поправил"   # пользователь правил поле руками
python3 agents/publisher/studio_fields.py streak [--channel <канал>]                     # выход 2.0: подряд без правки (цель 5)
python3 agents/publisher/upload.py publish/<канал>/<YYYY-MM-DD>/<slug>.md --dry-run   # всё проверить, ничего не слать
python3 agents/publisher/upload.py <slug> --dry-run                # то же по имени: последняя заметка slug
agents/publisher/.venv/bin/python agents/publisher/upload.py --authorize  # OAuth в браузере (в Testing — раз в неделю, CF-0589), токен вне репо
python3 agents/publisher/publisher_auth.py status [--needs-you]       # срок токена: 0 ок, 1 истекает за сутки, 3 переразрешить сейчас
python3 agents/publisher/api_switch.py status [--channel <канал>]                  # переключатель API-загрузки по каналам (CF-0607)
python3 agents/publisher/api_switch.py enable <канал> --by user --note "…"           # включить после аудита (предупреждения — в историю)
python3 agents/publisher/api_switch.py disable <канал> --by <кто> [--note "…"]        # выключить (Studio-путь работает всегда)
python3 agents/publisher/upload.py publish/<канал>/<YYYY-MM-DD>/<slug>.md  # загрузка, спросит «да» с терминала (только при включённом переключателе)
```

Порядок одного запуска — каждый шаг стоп, если не сошлось:

0. переключатель API-загрузки канала включён (`api_switch.py`, `CF-0607`) — иначе отказ
   одной строкой до любого обращения к Google (сухой прогон только говорит об этом);
1. метаданные из заметки `publish/<канал>/<день>/<slug>.md` — папка канала и дня выхода по МСК, ролик
   рядом; без слота — `publish/<канал>/_queue/` (раскладка `CF-0475`, `shared/runlog/publish_layout.py`)
   (`## Название`, `## Описание`,
   `## Теги`, `## Публикация`, `## Настройки`) — `publish_note.py`; и блок
   `## Утверждения` свежий для этих названия и описания — `note_claims.py` (`CF-0555`:
   название и описание прошли разбор и проверку следования `CF-0553`, у каждого
   утверждения цитата и ссылка; правила — `docs/publisher-metadata-rules.md`);
2. приёмка пользователя по имени ролика (`publish/acceptance-log.json`, `CF-0328`)
   и пометка публикации (`publish/publication-holds.json`, `CF-0318`): неподписанная
   пометка — жёсткий стоп, нечитаемый реестр держит всё — `upload_gate.py`;
   канал не на паузе (`publish/channel-pauses.json`, `CF-0569`) — `upload_gate.check_channel_not_paused`;
   готовая карточка `CF-0017` этой приёмки (`publish_card.card_state`), слот — её
   `## Публикация` (очередь `CF-0587`), день слота по МСК = папка дня; `--publish-at`,
   отличный от слота карточки, — отказ (`CF-0607`: то же, что заполнил бы Studio-путь);
3. ролик ещё не в журнале `publish/uploads.json` (ни через API, ни через Studio, ни переносом;
   и не в `api_data_deleted`, `CF-0618`);
4. токен OAuth и канал токена == `PUBLISHER_CHANNEL_ID` — `publisher_auth.py`,
   `youtube_client.py`;
5. **«да» пользователя с терминала** (`/dev/tty`, не stdin, флага нет) — `upload_gate.ask_user`;
6. `videos.insert`, resumable, `privacyStatus: private` + `publishAt`,
   `selfDeclaredMadeForKids: false` — `youtube_client.py`;
7. запись результата: журнал `publish/uploads.json`, строка в заметке ролика,
   ячейка в `publish/README.md` (строка той же папки, `` `<канал>/<день>/<slug>.mp4` ``) — `upload_records.py`.
   Заметка была в `<канал>/_queue/` — загрузчик напомнит `runlog publish assign <slug> --channel <канал> --apply`.
   Затем колонки публикации реестра ротации — `publish_window.record_published` (как у Studio-пути).

## API-путь: переключатель и как включить после аудита (`CF-0607`)

Код API-загрузки выпущен в 2.2, но функционал ждёт аудита YouTube API (`CF-0470`): без
него всё загруженное через `videos.insert` навсегда private. Поэтому у каждого канала
переключатель `api_upload`, **по умолчанию выключен**; включает пользователь после
одобрения — без нового релиза. Первая боевая загрузка (`CF-0585`) — действие после
аудита, не задача, держащая релиз.

- **Где.** `schedule/api-upload.json` (каталог состояния фабрики, gitignored, рядом с
  `switch.json` расписания), не `channels/*.json`. Единственный писатель —
  `api_switch.set_switch`: проверка, блокировка, атомарная запись, строка истории на
  каждую перемену (кто, когда, заметка, предупреждения).
- **Кто.** `enable` — только `--by user` и с `--note` (где и когда пользователь сказал);
  оператор вызывает его только по прямому слову пользователя в чате. `disable` — кто угодно.
- **Предупреждения при включении** (печатаются и пишутся в историю, но не блокируют —
  решение пользователя): OAuth-приложение ещё в Testing (`PUBLISHER_OAUTH_MODE`); таймер
  тика не установлен (plist нет в `~/Library/LaunchAgents` — срок удаления API Data
  `CF-0618` держится тиком, пробел 7 в `docs/api-audit/README.md`); токен истёк, скоро
  истечёт, без нужного scope или его нет.
- **Центр** (командный центр, `http://127.0.0.1:8790/publishing?channel=<канал>`, вкладка
  «Публикация»): строка переключателя и последние перемены; кнопка «Включить / Выключить
  API-загрузку» — сначала план (`POST /api/publish/<канал>/api-upload/switch/plan`, ничего
  не пишет, предупреждения видны до подтверждения), затем подтверждение
  (`…/api-upload/switch` → `api_switch.set_switch`, `by: user`, заметка с пометкой «из
  центра»); включение — только с заметкой и фразой «аудит подтверждаю», набранной самим
  пользователем в окне подтверждения.
- **Как включить после аудита** — раздел «После одобрения» в
  [`docs/api-audit/README.md`](../../docs/api-audit/README.md): `PUBLISHER_OAUTH_MODE=production`
  и новое `--authorize`, таймер тика, `api_switch.py enable <канал> --by user --note "…"`,
  затем `CF-0585`.

**Одна картина с Studio-путём.** API-путь берёт то же, что Studio-путь (`CF-0018`,
`studio_fields.prepare`): готовую карточку `CF-0017` этой приёмки, её слот очереди
`CF-0587` в своей папке дня, паузу канала `CF-0569` (`upload_gate.check_channel_not_paused`),
журнал `CF-0586` — строку пишет `upload_records.build_record` → `record()` с `source: api`,
слот в UTC (тот же момент, что Studio-строка в поясе канала). Поэтому гейт двойной загрузки
(`upload_gate.check_not_uploaded`, с `api_data_deleted`), `studio_fields.prepare` и очередь
(`publish_queue.occupants`, удалённые по политике API-строки держат свой день) видят одно и
то же, какой бы путь ни грузил. Studio-путь — запасной и работает при любом положении
переключателя.

**Принятие ролика в API-пути.** Как в Studio-пути: «да» пользователя в чате на ролик —
это приёмка (`runlog acceptance`, `CF-0328`; карточка встаёт в слот). Сама загрузка —
отдельное подтверждение в терминале: `upload_gate.ask_user` показывает сводку и
предупреждение ToS 9.1 (`TOS_NOTICE`, `CF-0618`) и ждёт «да» с клавиатуры (`/dev/tty`;
флага, который ответил бы за пользователя, нет). Без обоих «да» ролик не уходит.

## Токен OAuth: scope аналитики и недельный срок (`CF-0589`)

OAuth-приложение в режиме Testing (production — после `CF-0470`): Google держит
refresh-токен **7 дней** с момента согласия. Раз в неделю пользователь жмёт
«разрешить» (~30 с). Режим явный — `PUBLISHER_OAUTH_MODE=testing|production` в `.env`
(`CF-0607`, по умолчанию `testing`): в `production` у токена нет фиксированного срока
(действует, пока не отозван и используется; 6 месяцев без использования — истекает,
https://developers.google.com/identity/protocols/oauth2#expiration), `status` и центр
(«Токены») говорят «без фиксированного срока»; токен, выданный ещё в Testing, держит свои 7 дней, и
`status` просит переразрешить. Одно разрешение выдаёт все scope фабрики: `youtube.upload`,
`youtube.readonly` и `yt-analytics.readonly` (метрики Аналитика, `CF-0020`) —
`publisher_auth.SCOPES`.

**Команда пользователя** (точная, из `publisher_auth.AUTHORIZE_COMMAND`; в браузере
войти в аккаунт канала и оставить все галочки):

```
agents/publisher/.venv/bin/python agents/publisher/upload.py --authorize
```

После согласия рядом с токеном (вне репо) пишется `<токен>.state.json` (600): когда
выдан, в каком режиме (`oauth_mode`), когда истечёт (в Testing —
`PUBLISHER_TOKEN_LIFETIME_DAYS`, по умолчанию 7; в Production — `null`), какие scope
выданы — значения токена там нет.

**Кто зовёт `status`** — `python3 agents/publisher/publisher_auth.py status`, одна
строка и код выхода (как `publish_queue.py tomorrow`), сеть не трогает:

- оператор — в начале каждой сессии, с `--needs-you`;
- шаг метрик (`CF-0020`) — перед походом в Analytics API; код 3 — шаг не идёт;
- `upload.py --authorize` печатает её же после согласия.

| код | строка | что делать |
|---|---|---|
| 0 | `ok   oauth: токен YouTube действует ещё N ч, до … МСК` | ничего |
| 1 | `OAUTH EXPIRES SOON: … истекает завтра …` (за `PUBLISHER_TOKEN_REMIND_HOURS`, по умолчанию 24 ч) | напомнить пользователю, команда в строке |
| 3 | `OAUTH EXPIRED` / `NO AUTH` / `NO SCOPE` / `UNKNOWN EXPIRY` | шаги с YouTube стоят; пользователь выполняет команду выше |
| 2 | `OAUTH ERROR: …` | конфигурация (`.env`) |

`--needs-you` (только с ним) задаёт **один вопрос на срок** в журнале вопросов
(`shared/needs_you.py`, `CF-0652`; ключ `oauth-token:<срок> <состояние>`, каталог —
`--needs-you-dir`, иначе `NEEDS_YOU_DIR`, иначе `<корень>/needs-you`): повторный вызов
ничего не добавляет, новый срок или состояние решает старый вопрос и задаёт новый,
исправный токен решает вопрос (`resolve`). Отдельного Telegram журнал тут не шлёт —
его шлёт пуш токена ниже. `publisher_auth.NOTIFIERS` зовёт `notify()` для любого
статуса, кроме ok; там зарегистрирован пуш `CF-0591` (`_push` → `shared/notify.py`): одно
уведомление на срок и состояние со ссылкой на центр → «Токены»
(`http://127.0.0.1:8790/tokens`), повторный `status` того же
состояния ничего не шлёт ([`docs/notifications.md`](../../docs/notifications.md)).

**Истёкший или отозванный токен.** Refresh, на который Google ответил
`invalid_grant`, — `publisher_auth.TokenExpiredError` (подкласс
`ReauthorizeRequired`, `exit_code = 3`), отметка `invalid_grant_at` в состоянии,
`status` говорит EXPIRED до следующего согласия. Токен без нужного scope —
`MissingScopeError` до любого запроса к Google. Шаг ловит `ReauthorizeRequired`,
печатает строку и выходит с кодом 3 — батч не падает; `upload.py` так и делает
(`REAUTHORIZE: …`, код 3). Метрики берут учётные данные через
`publisher_auth.analytics_credentials(cfg)`; загрузка — через
`load_credentials(cfg)` (нужны только scope загрузки, старый токен без аналитики
грузит).

## Карточка публикации при приёмке (`CF-0017`)

Гриль 2.0 (06.10): пользователь говорит одно «да» на ролик — приёмку, и видит при
этом ролик **вместе с карточкой**. Принятие = «да» на публикацию ровно того, что в
карточке; `CF-0018` потом заполняет Studio её полями. Обложку не делаем (`CF-0477`,
ставит пользователь).

**Когда и кто.** Оператор (позже — оркестратор 2.2) строит карточку **после того,
как ролик готов (05, судья кадров 06), и до вопроса о приёмке** — для каждого
ролика, который показывает пользователю:

```
python3 agents/publisher/publish_card.py build pipeline/<канал>/<батч> <slug>
```

- Черновик названия, блока 1 описания, хэштегов и тегов пишет модель (`claude -p`,
  кэш `<батч>/work/publish-card/cache/`), или оператор файлом `--draft draft.json`
  (`{"title", "about", "hashtags", "tags"}`). Черновик — только предложение; одна
  переписка моделью, если проверки его отбили.
- Код собирает остальное из сценария и `channels/<канал>.json` → `publisher`
  (суффикс названия, строка источника, строка фактчека, хэштеги-константы, настройки —
  поканально; без блока `publisher` карточки у канала нет): описание ровно из трёх
  блоков, блок 2 — настоящий источник `production_fact.source_url` и фактчек каждой
  плашки `comparison_line_delivered[]` из 05 (формулировка + полная ссылка), и —
  когда утверждения ролика цитируют описание эпизода с TVmaze (`tvmaze_episode`,
  CC BY-SA 4.0, `CF-0636`) — строка атрибуции `publisher.attribution_line` со ссылкой
  на страницу эпизода (опорный текст темы — из 01 батча). Утверждение Wikidata
  (`wikidata_statement`, CC0, `CF-0637`) строки атрибуции не даёт; факт на нём
  назван в блоке 2 как `Wikidata, <Q> — <свойство>`.
  Футаж (`CF-0664`): `05` → `videos[].footage_credits[]` (VE-1) — по строке на
  источник с `attribution` `required`/`requested`, по шаблону
  `publisher.footage_attribution_line` (`{credit}`, `{url}`; `{license}`,
  `{license_url}`, `{changes}` — пустые сегменты `·` выпадают, у public domain
  лицензии нет); для CC BY / BY-SA в `{changes}` идёт `publisher.footage_changes_note`;
  для BY-SA — ещё строка `publisher.footage_share_alike_line` (ролик под той же
  лицензией). Без конкретного `credit`: `requested` — имя источника
  (`origin_name`), `required` — карточка не собирается (выдумывать подпись
  нельзя). `footage_credits` `[]`/`null` (Reel) — карточка прежняя.
  Партнёрская ссылка (`CF-0593`): у канала с блоком `affiliate` (сейчас только
  ExampleTech, выключен) `publish_card.affiliate_of` решает по `shared/affiliate.py`
  `decide`: ссылка ставится, только когда слот включён, предмет темы **и есть**
  продукт таблицы `channels/<канал>/affiliate.json` и факт сценария его называет —
  тогда в конец блока 2 строка `affiliate.link_line` и раскрытие
  `affiliate.disclosure` (одна ссылка на ролик). Решение с причиной — в маркере
  (`affiliate`: `placed`, `reason`, `detail`, продукт, программа) и строкой в
  `## Карточка`; подпись ссылки читает `note_claims.py`. Канал без блока — карточка
  прежняя, ключа в маркере нет.
- Затем сразу `note_claims.py` (`CF-0555`) на этой карточке: прошло — пишется
  `## Утверждения`, статус **готова**; нет — **НЕ готова**, причины в `## Карточка`.
- Выход: `<батч>/work/publish-card/<slug>.md` — это и есть заметка в формате
  `publish_note.py` (`## Название/Описание/Теги/Публикация/Настройки/Утверждения`) плюс
  `## Карточка` со статусом и маркером `<!-- publish_card {...} -->` для `CF-0018`.
  Команда печатает короткий вид — его показывают пользователю рядом с роликом
  (`publish_card.py show <карточка>` — тот же вид позже).
- Коды выхода: 0 готова; 1 собрана, но не готова (показывать как готовую нельзя —
  чинить название/описание или пересобирать ролик, если не прошли слова самого
  ролика); 2 не собрана (нет настоящего источника, плашка без ссылки, у канала нет
  блока `publisher` или нет `attribution_line` для цитируемого TVmaze; футаж с
  `attribution: required` без конкретного `credit` или без слов канала для него,
  `CF-0664`); 3 модель не спрошена (`NOT_LOGGED_IN`).

**После «принят»** (`runlog acceptance --record … --write` или кнопка центра — ролик кладётся
в копилку `publish/<канал>/_queue/` тем же шагом, что пишет вердикт: `acceptance.queue_accepted`,
`CF-0738`; `publish_path` — в том же коммите; принятый без места в `publish/` находит
`runlog acceptance --enqueue-accepted` — сухой прогон, `--apply --by --via` кладёт и запускает
сборку карточки, как при вердикте, `CF-0919`; совпадение имён решается само — `CF-0920`, см.
«Совпадение имён в копилке» ниже):

```
python3 agents/publisher/publish_card.py place pipeline/<канал>/<батч> <slug> [--replace]
```

кладёт **готовую** карточку рядом с роликом (`publish/<канал>/<корзина>/<slug>.md`);
не готовую — не кладёт. Ролик ждёт в `_queue/` и день не назван — та же команда ставит его
в **ближайший свободный слот канала** (`CF-0587`, см. «Очередь публикаций» ниже): пишет слот в
`## Публикация` карточки и переносит пару в `publish/<канал>/<день>/` (`publish_layout.assign`:
строка README и `publish_path` приёмки идут следом). Одна команда после «принят»; печатает
`slot: **YYYY-MM-DD 01:00 МСК** …`. `--no-slot` — оставить в `_queue/`; `--day` — явный день
(без очереди). **Ролик — этого батча** (`CF-0857`, `publish_layout.of_batch`): по `publish_path`
его строки приёмки, а не последнее место имени — у канала имена повторяются (23.10 Tech
`anthropic`: старый в `2026-10-23/`, новый в `_queue/`); `--day` — папка, где ролик **лежит**,
а не слот, куда его ставить (ролик в другой папке — отказ с тем, где он). Новой версии в
`publish/` ещё нет, а одноимённый старый есть — отказ, карточка поверх чужой заметки не
ложится. Тем же путём решение по карточке (`card_center.py`) и `upload.py --entry`. Дальше: `runlog profile --fill`, загрузка. Правка названия или
описания руками после сборки делает карточку не готовой (`card_state()`: отпечаток
блока `## Утверждения`) — до повторной проверки.

Агент (Claude) эту команду без `--dry-run` не запускает и «да» за пользователя
не вводит: у его оболочки нет терминала, и загрузчик откажет сам.

## Копилка канала (`CF-0738`)

Пользователь копит принятые ролики и потом ставит N штук на ближайшую неделю.
`publish_stash.py`:

```
python3 agents/publisher/publish_stash.py show --channel C [--json]      # копилка с подробностями
python3 agents/publisher/publish_stash.py plan --channel C SLUG...       # K роликов -> K ближайших слотов
python3 agents/publisher/publish_stash.py confirm --channel C SLUG... --base-sha256 H --by WHO --via WHAT
```

`stash()` — по каждому ролику в `_queue/` и в запасе `_reserve/` (`CF-0919`, поле `bucket`): батч или пересборка, когда принят, есть ли и готова ли
карточка, mp4 в `publish/` и превью в батче, удержание, давность (дни с приёмки и с даты новости
темы — `evidence.sources[].published_at` в 01 батча); `not_queued` — принятые без места с командой
починки. Правило старения (`CF-0741`, решение пользователя 13.10): возраст считается от даты
новости темы, если она есть, иначе (вечная тема) — от даты принятия (`age.basis` news/accepted,
`age.days`); старше 14 дней (`STALE_AFTER_DAYS`, 15-й день и дальше) — `age.stale`, в ответе `stale` —
сколько таких. Без обеих дат — `stale: null`. Устаревший только помечается: размещению не мешает,
в `place_plan`/`place_confirm` пункт несёт `stale`, `age_days`, `age_basis`.
`place_plan` / `place_confirm` — свободные слоты из `publish_queue.table`, каждый ролик ставит
`publish_card.place` (одна логика слота, окно `CF-0042`); отказы — по ролику, ответ в форме `CF-0726`.
`touched` ответа confirm — все файлы, которые он создал, изменил или убрал (пути от корня,
отсортированы; переезд пары — старый путь в `_queue/` и новый в папке дня), как их покажет
`git status`: снимок `publish/` и `rotation/ledger/` до и после под тем же замком приёмки
(заметки и журналы — по sha256, mp4 — по размеру и mtime; `*.lock` и dot-файлы не входят).
У `place_plan` и отказанного confirm — `touched: []`.

## Перенос и снятие размещённого ролика (`CF-0856`)

Размещение (`publish_card.py place`, копилка) ставит ролик в слот; обратного хода не было — 23.10
очередь сдвигали руками (коммит `09ba3029`). `publish_move.py` — та же форма одной командой:

```
python3 agents/publisher/publish_move.py --channel example-tech --unplace gemini \
    --move iphone-duo=2026-10-24 --move openai=2026-10-25 [--json]                 # план, ничего не пишет
python3 agents/publisher/publish_move.py --channel example-tech --unplace gemini \
    --move iphone-duo=2026-10-24 --move openai=2026-10-25 --apply --by user --via center [--base-sha256 H]
```

- `unplace` — ролик из папки дня, которого нет в Studio (нет живой строки `uploads.json`), уходит в
  `_queue/` (заметка + mp4, `publish_layout.unassign`: строка README и `publish_path` следуют),
  `## Публикация` = «Слот не назначен. Снят с <день> …» без жирного времени — очередь и копилка
  читают его как ждущий. Ролик в Studio не снимается (`in_studio`): его можно только перенести.
- `move` — на слот целевого дня канала; заметка называет новый слот жирным, пара переезжает
  (`publish_layout.move_day`). Если ролик уже в Studio — `upload_records.reschedule` правит
  `publish_at`/`publish_day`/`note` строки и дописывает перенос в `rescheduled` (откуда, куда,
  когда, by, via). Дату в самой Studio ставит человек или центр по слову пользователя — инструмент
  Studio не трогает, ответ напоминает об этом строкой `STUDIO`.
- План судится целиком: все названные ролики сначала уходят со своих дней, потом каждый перенос
  берёт слот цели — сдвиг «25→24, 26→25» со снятием 24-го не конфликт, порядок аргументов не важен.
  Отказы по ролику: `day_taken`, `no_slot_day`, `too_soon`, `published` (слот уже прошёл),
  `not_found`, `in_queue`, `in_studio`, `same_day`, `bad_day`, `ambiguous`, `inconsistent`;
  сверху — `bad_who`, `unknown_channel`, `no_queue`, `empty_order`, `batch_open`,
  `check_changed`, `apply_failed`, `commit_refused`. Окно паттернов (`check_candidate`) спрашивается
  о каждом переносе с остальными роликами плана на их новых местах — только предупреждения.
- `--apply` — всё или ничего, под замком приёмки, один коммит ровно тронутых файлов
  (`git_commit.commit_paths`, mp4 вне git). Реестр ротации не трогается: его дневные колонки
  заполняются только у вышедших роликов, а вышедший не переносится.
- Для центра: `publish_move.move_plan(channel, moves, unplace, root, now)` и
  `move_confirm(channel, moves, unplace, by, via, root, now, base_sha256)`; ответ в форме `CF-0726`.

## Горизонт ленты и запас бессрочных (`CF-0918`)

Политика пользователя 04.11: «делать видео вперёд только на 3 дня, чтобы выкладывать актуальные
новости; иметь запасной пул бессрочных». Что из неё в коде:

- **Горизонт постановки** = `min_feed_days` канала (`batch_schedule.window_config`: DEFAULTS <
  `channels/<id>.json` `batch_schedule` < центр `schedule/channel-settings.json`; сейчас 3 у Reel и
  Tech). `publish_queue.horizon(channel, root, now)` → `{days, last_day, source}`, `last_day` —
  сегодня МСК + `days`. Сам по себе ролик дальше горизонта не ставится: `publish_queue.plan_slot`
  (а с ним `publish_card.py place` и автопостановка после приёмки) оставляет его в `_queue/` с
  причиной `beyond_horizon: …` в отчёте; `publish_stash.py plan/confirm` отказывает код `no_slot`
  (его центр знает) со строкой `beyond_horizon: …` и полем `beyond_horizon: true`. Ручной
  `publish_move.py --move` за горизонт — предупреждение `HORIZON`, не отказ: день назвал человек.
- **Горизонт ≠ порог батча** (`CF-0922`): нужен ли батч, тик решает по отдельной настройке
  `batch_feed_days` (по умолчанию 14, не меньше `min_feed_days`; `settings --batch-feed-days N`).
  Горизонт в 3 дня утро заполняет из запаса, и при пороге, равном горизонту, батч не запускался
  вовсе (06.11). Горизонт постановки по-прежнему только `min_feed_days`.
- **Снятие залитого в запас** — `publish_move.py --withdraw SLUG`: ролик в Studio (живая строка
  `uploads.json`) со слотом впереди. Studio-часть (отложенная публикация → «Ограниченный доступ»)
  делает человек или центр по слову пользователя ДО записи; инструмент пишет данные после:
  пара note+mp4 → `_reserve/` (`CF-0919`, `publish_layout.unassign`), `## Публикация` = «Слот не назначен. В
  Studio: ограниченный доступ, video_id … — снят с <день> в запас …», строка журнала —
  `upload_records.withdraw`: `withdrawn {at, by, via, task, from_at, from_day, from_note, studio}`,
  `publish_at`/`publish_day` = null, `note` → `_reserve/`, шаг в `rescheduled` (`to_at: null`,
  `withdrawn: true`). Можно вместе с `--move`/`--unplace` в одном плане: снятие освобождает день
  (`--withdraw exponential-time-hypothesis --move ipad-mini=2026-11-05`). Отказы снятия
  (`publish_move.WITHDRAW_REFUSALS`; центр шлёт снятие с договора 0.78.0, `CC-0179`): `not_in_studio` (не в Studio — это
  `--unplace`), `in_reserve` (уже снят), `not_placed` (нет пары в папке дня), `reserve_taken` (только
  остаток правила `CF-0920`: заняты и имя, и `<slug>~<батч>`, или батч неизвестен); прошедший слот —
  `published`. `--unplace` снятого — `in_queue`; `--unplace` залитого подсказывает `--withdraw`.
- **Снятая строка не слот**: `upload_records.is_withdrawn` / `holds_slot`. Её не считают
  `publish_queue.occupants` (лента, `table`, `next_free`), `publish_window.feed` и
  `published_rows`, `factory_state` (слоты «в Studio»), `pool_release` (исходники снятого не
  освобождаются — он не вышел), аналитик (`metrics.plan` — пропуск `withdrawn`). Планировщик
  батчей не засчитывает запас (`publish_queue.reserve`) в виртуальное заполнение ленты — считает
  `publish_queue.queued`, имена в `_queue/` без снятой строки: снятие дальних дней → лента короче
  `batch_feed_days` (`CF-0922`) → `needs_batch`, а новый одноимённый ролик в `_queue/` считается как обычный.
- **Запас лежит отдельно от очереди** (`CF-0919`) — `publish/<канал>/_reserve/`, пара note+mp4.
  Иначе снятый ролик занимал имя в `_queue/` и мешал приёмке нового одноимённого
  (хайп-повтор франшизы, percy-jackson 04.11). Копилка читает оба места: `publish_queue.waiting`,
  `reserve_entries` (снятая строка журнала + её пара: `_reserve/`, а до миграции — `_queue/`, если
  заметка того же батча), `publish_stash.stash`; `--move` и `--auto` возвращают оттуда в день. Один
  ролик в копилке и один в запасе с одним именем — два ролика: `plan`/`confirm` по голому имени
  отказывает с подсказкой `БАТЧ/SLUG`, `--auto` называет сам, `--move` по имени возвращает ролик
  запаса (при живом одноимённом на дне — `ambiguous` и подсказка `--move БАТЧ/SLUG=ДЕНЬ`).
- **Миграция снятых до `CF-0919`** — `publish_move.py --channel C --migrate-reserve` (сухой прогон;
  `--apply --by WHO --via WHAT [--base-sha256 H]` пишет): пара → `_reserve/`, строка README и
  `publish_path` следуют, `note` строки журнала — на новый путь; `withdrawn.from_note` и шаги
  `rescheduled` не меняются. Один коммит; пока идёт батч — `batch_open`; имя уже в `_reserve/` —
  пара ложится как `<slug>~<батч>` (`CF-0920`); повтор — «nothing to migrate». Миграция больше не
  обязательна перед приёмкой: мешающий снятый ролик приёмка уносит сама.
- **Совпадение имён в копилке** (`CF-0920`) — не уровень пользователя (его слова 04.11; поручение
  25.10): решается автоматически, в Telegram не идёт. Правило `acceptance.queue_accepted`:
  - имя в `_queue/` держит **снятый** ролик (строка журнала `withdrawn`, остаток старой раскладки) —
    пара уходит в `_reserve/` отдельным коммитом «Запас <канал>: …» (README, `publish_path`, `note`
    журнала следуют; в ответе `reserve_move`), новый получает имя; пока идёт батч и в голом
    `--record --write` коммитить нельзя: снятый остаётся, новый ложится под суффиксом;
  - имя держит **живой другой** ролик (другой батч/сценарий) — он не трогается, новый ложится как
    `publish/<канал>/_queue/<slug>~<батч>.mp4 + .md` (в ответе `name_taken`) и идёт как обычно:
    карточка, план, заливка, README, журнал;
  - то же в `_reserve/`: `--withdraw` и миграция кладут второго как `<slug>~<батч>`, вернуть его —
    `--move БАТЧ/SLUG=ДЕНЬ` (голое имя при двух — `ambiguous`), `--auto` называет сам.
  **Суффикс — имя файла, не ролика.** `slug`, `entry_id`, карточка, план, журнал загрузок и тайтл —
  с голым именем; только `publish_path` и `note` называют файл. Читатели: `publish_layout.entries`
  отдаёт `slug` (голое), `stem` (файл), `batch` (суффикс), `batch_of(e)` — батч пары (заметка, иначе
  суффикс), `at_path`, `of_batch`, `free_stem`, `note_rel`; `assign/to_reserve(stem=)` или
  `assign x~батч` выбирают из двух. Папка дня суффикса не несёт: в день пара уходит под голым именем,
  а если в этот день такое имя уже есть — `LayoutError`, как раньше (в дне одно имя один раз: так
  считает `publish_queue.table`). `publish_card.place`, `publish_stash`, `publish_move`,
  `studio_fields.locate`, `upload` читают через это.
  **Уведомления.** `slug_taken` (заняты и имя, и файл с суффиксом — почти не бывает) на шину не идёт
  (`acceptance.LEFT_OUT_QUIET`): остаётся в ответе (`left_out`, `alert_ru`), в `stash.not_queued`
  (триаж центра) и в журнале `notify/stash-events.jsonl` (`moved_to_reserve`, `named_by_batch`,
  `slug_taken`, `other_version_placed` — для драйвера, без бэкендов). `CF-0921`:
  `other_version_placed` (принята другая версия уже размещённого ролика) тоже не на шине — пишется
  в журнал на вердикте; если правило не отличило новый ролик от версии (в записи нет темы или
  факта, `acceptance.VERSION_UNSURE`), строка попадает в `stash.other_version` и в
  `publish_stash.py show` («ВЕРСИЯ ИЛИ НОВЫЙ?») с командой `--other-version-ok` — решает драйвер.
  `batch_missing`, `render_missing`, `channel_unknown`, `queue_failed` по-прежнему `needs_human`.
- **Возврат из запаса** — без перезаливки: `publish_move.py --move SLUG=ДЕНЬ` или
  `publish_stash.py confirm` (оба через `publish_move.return_reserve`): заметка называет слот
  жирным («возвращён из запаса копилки»), пара → папка дня, `upload_records.reschedule` снимает
  `withdrawn` и пишет шаг `from_reserve`. В Studio ставят «Отложенная публикация» на этот слот —
  строка `STUDIO` ответа. Сама очередь ролик из запаса не ставит (`plan_slot` отказывает, в
  подмену окна CF-0042 он не идёт).
- **Новость или бессрочное** (`CF-0919`, `fact_kind.py`, поля ролика в `publish_stash.stash`) —
  по факту ролика (название, описание, `## Утверждения` заметки; без заметки — `claims[].text`,
  `story_claims[].text`, `narration` 03), а не по датам источников: `news`, если есть будущее время
  («will», «is due», «upcoming», «coming», «is slated to» — `fact_kind.FUTURE_RE`), дата впереди, или
  в названии/описании дата с годом не старше 60 дн. от приёмки; иначе `evergreen`. `news_why`;
  `stale_at` — дата впереди, иначе дата новости (свежая из текста, источник, приёмка) + 14 дн.;
  `reserve`/`video_id` — ролик запаса. Бессрочный не стареет: `stale_at` нет, правило `CF-0741` к
  нему не применяется, `--auto` его не пропускает. Спорный вид ставит драйвер руками:
  `publish_stash.py kind --channel C SLUG news|evergreen --by WHO --via WHAT` (журнал
  `publish/feed-kinds.json`, поле `kind_mark`). `show` печатает это и горизонт.
- **Порядок постановки** — `publish_stash.py plan|confirm --channel C --auto [--force]`
  (`choose`): сначала свежие новости, ближайшая к устареванию первой (по дате новости, иначе
  приёмки), потом бессрочные из запаса (старые по приёмке первыми); столько, сколько свободных
  слотов в горизонте, остальное ждёт (`skipped`: `beyond_horizon`). Устаревшая новость в автовыбор
  не идёт (`skipped`: `stale_news`) без `--force`. Ролик без готовой карточки в автовыбор не идёт
  (`CF-0919`, `skipped`: `no_card`, `card_building`, `card_not_ready`, `note_differs` — те же коды,
  что у постановки; `--force` этого не отменяет), его слот занимает следующий; ролик запаса не
  проверяется — его заметка уже карточка. Даты сравниваются как дни, а не строками; названная руками (`plan SLUG`, `publish_move
  --move`) ставится с предупреждением `STALE`.

## Карточка из центра (`CF-0747`)

Карточку больше не собирает только оператор. `card_center.py`:

```
python3 agents/publisher/card_center.py build --channel C --batch B SLUG --by WHO --via WHAT [--draft FILE]
python3 agents/publisher/card_center.py result RUN_ID|LOG
python3 agents/publisher/card_center.py state --channel C --batch B SLUG
python3 agents/publisher/card_center.py ruling-plan --channel C --batch B SLUG
python3 agents/publisher/card_center.py ruling-confirm --channel C --batch B SLUG --base-sha256 H --by WHO --via WHAT --words "слова пользователя"
```

- При приёмке (там, где `CF-0738` кладёт ролик в `_queue/`) сборка `publish_card.py build`
  стартует сама отдельным процессом со своим журналом (`schedule/publish-card/runs/`); не
  вторая, пока идёт первая, и не поверх готовой карточки того же сценария.
  `PUBLISH_CARD_AUTOBUILD=0` выключает (так делают раннеры тестов).
- `build` из центра — пересборка по нажатию, по желанию с черновиком `{title, about, hashtags, tags}`
  (идёт как `--draft`); `result` — итог: ready / not_ready / refused / not_asked / error / running.
- Копилка показывает состояние карточки: none / building / ready / ruled / not_ready, причины, журнал.
- Решение пользователя по не готовой карточке (`ruling-plan` / `ruling-confirm`): только когда не
  прошли утверждения самого ролика (озвучка, надпись), никогда — когда не прошло утверждение
  названия, описания или тегов или есть другая проблема карточки. Пишет `## Решение пользователя`
  (слова, кто, через что, когда, не прошедшие утверждения) и кладёт карточку рядом с роликом
  (`## Публикация` уже лежащей заметки сохраняется). `publish_card.card_status` → `ruled`;
  `place`, копилка, `studio_fields.py`, `upload.py` берут её как готовую; правка названия или
  описания после решения его снимает.

`publish_card.py build` шлёт «ждёт приёмки» только для ролика без вердикта в записи приёмки
(`CF-0748`): пересборка карточки принятого или отклонённого ролика уведомления не шлёт.

## Очередь публикаций канала (`CF-0587`)

Гриль 2.0 (06.10, Q7): принятый ролик сам встаёт в ближайший свободный слот канала;
`publish/<канал>/<день>/` — отражение очереди на диске. Модуль — `publish_queue.py`.

**Слот — из канала, не из кода**: `channels/<канал>.json` → `publisher.slot`
(`{"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}`; при `per_day` > 1 —
`times`, по времени на слот). Нет блока — у канала нет очереди: `place` оставляет ролик в
`_queue/` и говорит об этом. Папка дня — всегда день по МСК, в который попадает слот (`CF-0475`),
какой бы ни был пояс канала.

**Занято** — по записям, не по памяти: ролик в папке дня (время из его `## Публикация`, иначе
этот день) и живая строка журнала `publish/uploads.json` (`publish_at`, иначе `publish_day`) —
так держит слот и ролик, который уже стоит в Studio, даже если его папка ушла в архив. Строка с
`removed_at` слот не держит. Ближайший свободный — не раньше чем через `lead_hours`: сегодняшний
01:00 после полуночи ещё может быть свободен, днём — уже нет, и очередь берёт завтра.

**Постановка** (`plan_slot`, её зовёт `publish_card.py place`): ролик принят и без открытого
удержания (`acceptance-log.json`, `publication-holds.json` — иначе отказ, ролик остаётся в
`_queue/`); канал не на паузе; проверки кандидата согласны. Две точки расширения:
- `PAUSE_CHECKS` — `CF-0569` (флаг паузы канала, `channel_pause.queue_check`, ниже): `(channel,
  root, now) -> None | причина | {"reason"?, "notice"?}`; причина — ничего не ставится (`Paused`),
  `tomorrow` отвечает `PAUSED` (код 3); `notice` (истёкшая пауза) не держит, но идёт строкой
  `PAUSE …` в `warnings` и в строку `tomorrow`;
- `CANDIDATE_CHECKS` — в ней окно паттернов `CF-0042` (`publish_window.candidate_check`, ниже):
  `(channel, slug, slot, root, now, ctx) -> None | {"verdict": "reorder" | "warn", "reason"}`,
  `ctx` = `{"batch_id", "moved"}` (`moved` — другие ролики плана и их новые слоты).

## Пауза публикаций канала (`CF-0569`)

Флаг паузы ставит и снимает оператор или пользователь; Publisher только слушается флага:

```
python3 agents/publisher/channel_pause.py set --channel example-film --by user \
    --reason "<причина, словами пользователя, с датой>" [--until 2026-10-20]
python3 agents/publisher/channel_pause.py clear --channel example-film --by user --note "<почему снята>"
```

Причину пишем словами пользователя и с датой; `--until` — только если пользователь назвал
срок (дата = с 00:00 МСК этого дня публикации снова идут; ISO-время с зоной тоже можно), иначе
пауза бессрочная — до `clear`. После `set`/`clear` — `show` и строка пользователю.

**Где лежит и почему там.** `publish/channel-pauses.json` — рядом с остальными реестрами
состояния публикаций (`acceptance-log.json`, `publication-holds.json`, `uploads.json`).
Это состояние, а не настройка — поэтому не `channels/<канал>.json` (конфиг канала, правится
руками и ревьюится как настройки); и не `publish/<канал>/` (это картинка очереди на диске:
папки дней, их перебирает `publish_layout` и уносит месячный архив `CF-0476`). Один файл на
все каналы — вся история пауз одним чтением. **Единственный писатель и читатель** —
`channel_pause.py`; остальные зовут его функции.

Строка: `pause_id` (`<канал>/<set_at>`), `channel`, `by` (`user` | `monitor` | `operator`
| …), `reason`, `set_at` (UTC), `until` (ISO с зоной или `null` — бессрочно), `cleared_at`,
`cleared_by`, `clear_note`. Строки не удаляются: снятие заполняет `cleared_*`, история
остаётся. У канала не больше одной открытой паузы: вторая — отказ, `--replace` закрывает
прежнюю с пометкой «заменена».

**Состояния** (`channel_pause.status`): `paused` — открыта и `until` нет или впереди;
`expired` — открыта, но `until` прошла: **не держит, но говорится** везде (строка `PAUSE …
ИСТЕКЛА`, пока запись не закрыта `clear`); `free`. Нечитаемый реестр — пауза для всех каналов
(fail closed, как реестр удержаний); отсутствующий — паузы нет.

**Кто слушается** (одна функция `channel_pause.gate(channel, root, now) -> (причина, notice)`):
- очередь — `publish_queue.PAUSE_CHECKS`: `plan_slot` бросает `Paused`, `tomorrow` — `PAUSED`,
  код 3; `show`/`next` пишут `PAUSED`;
- `publish_card.py place` на паузе — **оставляет карточку и ролик в `_queue/`**, печатает
  строку `PAUSED …` с причиной и завершается успешно (карточка на месте, слот ждёт снятия);
- загрузка — `upload_gate.check_channel_not_paused(channel, root, now)`: `upload.py`
  (`CF-0421`/`CF-0585`) зовёт её до `videos.insert`, отказ — ничего не загружается;
- **Studio-путь `CF-0018` обязан вызвать `upload_gate.check_channel_not_paused` до заполнения
  расписания в Studio** (после «загрузил X», до полей и времени): отказ (`GateError`) — расписание
  не ставится, ролик остаётся неопубликованным черновиком, пользователю — причина паузы;
  вернула строку (истёкшая пауза) — показать её пользователю и продолжать.

## Окно неповторения паттернов по опубликованной ленте (`CF-0042`)

Решение `CF-0015`, гриль 2.0 (06.10): ревьюер YouTube смотрит ленту канала подряд, поэтому
«в любых K подряд роликах ленты K разных пар (паттерн, ритм)» обеспечивается при постановке в
слот, а не на назначении (ротация `CF-0040` держит ровным только пул). Модуль — `publish_window.py`.

- **K — канала**: `channels/<канал>.json` → `patterns.rotation.no_repeat_window_k` (то же число,
  что у ротации), с потолком по числу собираемых пар (`rotate.effective_k`); дефолта в коде нет.
  Нет блока — окно не проверяется, постановка идёт с предупреждением.
- **Лента** — всё, что держит день канала (`publish_queue.occupants`: папки дней + живые строки
  `uploads.json`), по времени слота: прошлое — опубликовано, будущее — запланировано; строка
  журнала = ролик уже в Studio.
- **Пара ролика** (`pair_of`): `05-video-editor.json` его батча (`*_delivered`, иначе
  `*_requested` — паттерн это структура сценария, деградация монтажа её не меняет) → `03` того же
  батча → строка реестра ротации (пересборка — через `rebuild_of`, архивный батч — по
  `video_path`). Ничего не нашлось — **нет данных**: не догадка, а предупреждение с именем ролика,
  слот не задерживается.
- **Конфликт — перестановка внутри очереди, расписание не сдвигается** (публиковать реже хуже,
  чем опубликовать другой ролик). `plan_slot` по порядку:
  1. обмен с роликом, запланированным в более поздний слот и **ещё не стоящим в Studio** (папка
     дня без живой строки журнала): он выходит раньше, кандидат — в его слот, если оба без повтора;
  2. замена из `_queue/`: принятый, без удержания, с заметкой (строка `Батч`) ролик без повтора
     занимает слот; кандидат — в следующий свободный, если там без повтора, иначе остаётся в
     `_queue/` до следующей постановки (слот всё равно занят);
  3. **переставлять не с чем** — кандидат всё равно ставится в слот, а в плане громкая строка
     `WINDOW <канал>: <slug> ставится в … С ПОВТОРОМ ПАРЫ - … - переставить не с чем …; слот не
     сдвигается`. Решение гриля: пустой день хуже повтора, а молча — хуже всего.
  Ролик, уже стоящий в Studio по журналу, не двигается никогда: его расписание выставлено там.
- **Куда идут строки**: `publish_card.py place` печатает `note` (что с чем переставлено),
  `WARNING …` (повтор, нет данных, нет K) и `moved …`; оператор сессии (позже оркестратор 2.2)
  несёт строки `WARNING WINDOW` и «нет данных» в отчёт сессии пользователю. Повторы часто —
  чинить распределение пула (`CF-0040`, 1.3.3), не логику очереди.
- **Колонки публикации реестра ротации** (`rotation/ledger/<канал>.csv`: `published_at`,
  `feed_position`, `video_id`) — производные журнала `uploads.json`: `record_published` после
  каждой постановки (`place`) и по `publish_window.py record` пишет их через единственного
  писателя реестра (`Ledger.enrich`, только пусто → заполнено) по строгому ключу (батч, сценарий);
  ролик без строки реестра перечисляется, не угадывается; несовпадение — `conflicts`, не ошибка.
- **`check`** — лента с парами и все повторы внутри K (выход 1 при повторе) — сухой прогон для
  разбора; **`CF-0019`** (дедуп тем у охотника) — другой слой: снимает тему до производства, окно
  только переставляет готовые ролики, не выбрасывает их; друг друга не задевают.

**Пустой завтрашний слот.** `python3 agents/publisher/publish_queue.py tomorrow [--channel <канал>]`
— по строке на канал со слотом: слоты от сейчас до конца завтрашнего дня (пояс канала).
- `ok   example-film: 2026-10-07 01:00 МСК harbourlights` — выход 0;
- `PUBLISH QUEUE example-film: EMPTY SLOT 2026-10-11 01:00 МСК - nothing is scheduled there;
  publish/example-film/_queue/ holds N …` — выход 1;
- `PUBLISH QUEUE <канал>: PAUSED - <причина> …` — выход 3; 2 — у канала нет/сломан `publisher.slot`.

Кто зовёт и где показывает: оператор сессии (позже оркестратор 2.2) — в начале сессии и после
каждой приёмки; строку `EMPTY SLOT` он несёт **в отчёт сессии пользователю** (вместе с тем,
что лежит в `_queue/` и какой батч может закрыть слот). Код сам `NEEDS-YOU` и задачи не пишет:
решение «пересобрать / принять запасной / оставить день пустым» — пользователя, и в `NEEDS-YOU`
строку переносит оператор, только если пустой слот завтра нечем закрыть. С `--notify`
(`CF-0591`) пустой слот — ещё и одно уведомление пользователю (ссылка на центр →
«Публикация», `http://127.0.0.1:8790/publishing?channel=<канал>`); тот же набор пустых слотов при повторном вызове не шлётся. Уведомления шлют и
`publish_card.py build` (готовая карточка — ролик ждёт «да») и `studio_fields.py prepare`
(карточка готова к заливке — с `CF-0925` только в журнал, не в Telegram; с `--uploaded` — не шлёт: файл уже в Studio, `CF-0857`), а `studio_fields.py record` — «📤 <канал>: «<тайтл>» стоит на <дата> 01:00» в Telegram (`CF-0925`); всё — [`docs/notifications.md`](../../docs/notifications.md).
`show` — таблица слотов на `--days` дней со стрелкой у ближайшего свободного; `next` — одна строка.

## Журнал загрузок `publish/uploads.json` (`CF-0586`)

Машинная запись «этот ролик на канале под этим `video_id`» — ключ джойна аналитики 2.1
(`CF-0020`/`CF-0021`). Строка на ролик, поканально; пишет и читает **только**
`upload_records.py` — у Studio-пути, API и переноса один формат и одна функция `record()`.

Поля: `channel`, `entry_id` (строка приёмки в `acceptance-log.json`, обязательна),
`batch_id`, `topic_id`, `slug`, `video_id` (11 символов), `url`, `publish_at` (ISO с
явным смещением, `2026-10-08T01:00:00+03:00`; `null`, если слот нигде не записан — причина в
`gaps`), `publish_tz` (IANA: `Europe/Moscow` — пояс Studio канала, или `UTC` от API),
`publish_day` (день выхода по МСК = папка дня `CF-0475`), `note` (заметка-карточка или её
указатель в архиве Archive), `source` (`studio` / `api` / `backfill`), `recorded_at` (UTC);
необязательные — `superseded_video_ids` (удалённые прежние загрузки того же ролика),
`gaps`, `evidence`, `removed_at`/`replaced_by`, поля API (`title`, `privacy_status`, …);
у Studio-строк — `user_edited` (`false` при записи; `true` + `user_edited_at`/`user_edit_note`,
когда пользователь правил поля руками — счётчик выхода 2.0, `CF-0018`).

Запись идемпотентна: та же строка (канал, entry, slug, id, слот) ещё раз — no-op; тот же
`video_id` у другой строки — `DuplicateVideoId`; второй живой ролик одной приёмки — только
с `--replaces <старый id>` (старой строке — `removed_at`). Строки не удаляются.

**Где пишется.**
- Studio-путь (`CF-0018`): `studio_fields.py record` (сверка с карточкой и эта запись одной
  командой, «Путь через Studio» ниже); вручную, после того как поля в Studio сверены —
  `python3 agents/publisher/upload_records.py studio --channel <канал> --entry <канал/батч/slug>
  --video-id <id> --slot 2026-10-08T01:00+03:00` (или `--slot "2026-10-08 01:00 МСК"`; слот
  без пояса — отказ; день слота по МСК должен совпасть с папкой дня; `--dry-run` — проверка).
- API (`upload.py`, `CF-0421`/`CF-0585`): `upload_records.build_record` → `record()`.
- Перенос (`backfill_uploads.py`): всё, что вышло или запланировано в Studio до журнала.
  `python3 agents/publisher/backfill_uploads.py` — сухой прогон (план, «уже в журнале»,
  неразрешённые); `--write` — запись. Идемпотентен и **перезапускаем**: на релизе 2.0 его
  прогоняют ещё раз против `main` (`--root <корень main>` — там к тому времени новые ролики),
  записываются только новые; неразрешённые (нет `video_id`, нет приёмки, противоречия
  заметки и README, слот не в своём дне) не пишутся — их список идёт пользователю.
- Проверка журнала целиком — `upload_records.py check`; список — `upload_records.py show`.

`publish/README.md` и заметки остаются прозой для человека; id в прозе дублирует журнал, но
читает машина только журнал.

## Путь через Studio (`CF-0018`)

Гриль 2.0 (06.10): пользователь сам перетаскивает файл(ы) в Studio (ради качества — так
YouTube берёт исходник без пересжатия нашим клиентом) и пишет «загрузил X». Дальше всё делает
оркестратор через Claude in Chrome: поля из карточки `CF-0017`, расписание на слот очереди
`CF-0587`, сохранение, **перечитывание**, сверка, строка журнала. «Да» этого пути — приёмка
ролика (слово пользователя о конкретном ролике с карточкой перед глазами,
`publish/acceptance-log.json`); `/dev/tty`-«да» — только у API-пути (`CF-0585`).
Скрипт `agents/publisher/studio_fields.py` готовит поля и сверяет прочитанное — **сам он в
Studio не ходит**; страница — руками оркестратора, по граблям формы
(`docs/publisher-metadata-rules.md`, «Операционные заметки по Studio»).

**Разрешения.** Действия в Studio — только в сессии, где пользователь сам написал «загрузил
X» (или иначе явно поручил публикацию этих роликов). Перед первым «Сохранить» оркестратор
пишет одну строку — какие ролики на какие слоты (`X → 08.10 01:00 МСК`) — и ждёт «да»
пользователя в чате, если его сообщение уже не было таким поручением («загрузил X, ставь»).
Кнопку **«Опубликовать сейчас» / доступ «Открытый» не нажимать никогда** — только
«Запланировать» на слот карточки. Удалить ролик, поменять настройки канала, принять
соглашение в Studio — не делать, а сказать пользователю.

**Порядок на один ролик** (на несколько — тот же порядок для каждого по очереди; ошибка на
одном не останавливает остальные, итог — одной строкой на ролик):

1. `python3 agents/publisher/studio_fields.py prepare <slug> --channel <канал> --uploaded`
   (или путь заметки; `--uploaded` обязателен на Studio-пути: пользователь уже сказал «загрузил»,
   уведомление «загрузите файл» ему не шлётся — `CF-0857`, 23.10 anthropic). Голое имя, у
   которого в `publish/` несколько мест: места, уже записанные в журнал загрузок, отпадают;
   осталось одно — оно, несколько — отказ, назвать `--day` (`CF-0857`). Код 2 — отказ, причина в выводе:
   карточка не готова (нет маркера / собрана «не готова» / название или описание правили
   после сборки), нет строки приёмки `accepted`, стоит удержание `CF-0318`, **канал на паузе**
   (`upload_gate.check_channel_not_paused`, `CF-0569` — до любого расписания в Studio), ролик
   уже в журнале (перезаливка — `--replaces <старый id>`), у карточки нет слота / слот в прошлом
   / слот не в своей папке дня. Отказ → пользователю одной строкой, Studio не трогать.
   Непустой `ask_user` → спросить пользователя про эти поля **до** формы (ответ потом —
   строкой в `channels/<канал>.json` → `publisher.settings`).
2. В Studio: Контент → вкладка **Shorts** (черновики лежат там) → черновик с названием
   `studio_draft_title` (Studio называет черновик по имени файла `file_name` без
   расширения). Два черновика с одним именем или ни одного — стоп, спросить пользователя.
3. Заполнить по JSON: `title` в поле названия; `description` — поле описания это
   `contenteditable` DIV: клик → `Cmd+A` → печать (`form_input` на нём падает; **`Escape` в
   нём закрывает весь диалог**; подсказку хэштегов гасить кликом в стороне); «Развернуть» →
   теги — строка `tags_input` (через запятую, `tags_length` ≤ 500); вопросы `form`: аудитория
   (`made_for_kids`), «Использование ИИ» (`altered_content`), реклама (`paid_promotion`),
   галочка «Автоматическое объяснение понятий» (`auto_concepts: false` — снять), язык.
4. Доступ → «Запланировать» (`visibility_studio`): кнопка «Часовой пояс» → `zone_label`
   (сверять по `zone_offset`, `(GMT+03:00)`; по умолчанию Studio берёт пояс Mac — ставить
   явно); дата в календаре (`date`; текст пикера должен стать `date_picker_text`), время
   текстом `Cmd+A` → `time` → `Enter`. Сохранить. В окне подтверждения и в списке Shorts
   время показано в МСК (`schedule.msk`) — это норма.
5. **Перечитать со страницы** (открыть ролик заново, не из памяти о том, что печатали) и
   сложить в JSON (`scratchpad/studio-read-<slug>.json`):
   `{"title", "description", "tags": [...], "visibility": "<текст статуса>",
   "schedule": {"date_text": "<текст пикера>", "time": "<поле времени>", "zone_text":
   "<кнопка пояса>"}, "made_for_kids": false, "altered_content": false, "url": "<ссылка
   ролика>"}` — описание через `innerText` DIV, теги — подписи чипов. Время можно дать и
   `publish_at` ISO со смещением; время без пояса — расхождение.
6. `python3 agents/publisher/studio_fields.py verify <slug> --read <json>` →
   `ok` (0) или строки `MISMATCH <поле>: card … | Studio …` (1). Нормализация (что Studio
   меняет сама и что сверка прощает): NFC, `\r\n`→`\n`, NBSP/узкий пробел → пробел,
   невидимые нулевой ширины — вон, хвостовые пробелы строк, 3+ перевода строки → 2;
   название — пробелы схлопнуты в один; теги — списком по порядку; время — как момент
   (прочитанное в поясе Нью-Йорка тоже сходится). **Расхождение** — один раз исправить поле
   в Studio и перечитать; не сошлось снова — сказать пользователю до выхода ролика (поле,
   карточка, Studio, слот), журнал не писать.
7. `video_id` — из ссылки ролика (`youtube.com/shorts/<id>` или `studio.youtube.com/video/<id>/…`,
   11 символов). `python3 agents/publisher/studio_fields.py record <slug> --video-id <id>
   --read <json>`: снова сверка (расхождение — отказ, ничего не пишется), затем
   `upload_records.record_studio` (`source: studio`, `user_edited: false`) и
   `publish_window.record_published` (колонки публикации реестра ротации — заполнятся, когда
   слот пройдёт: их доводит любой следующий `record` или `place`). Повтор — `exists`, ничего
   нового. Чужой id в `url` прочитанного — отказ.
8. Пользователю одной строкой: `X → запланирован на 08.10 01:00 МСК, youtube.com/shorts/<id>,
   серия без правки 3/5`.
9. **Заодно прочитать Studio (`CF-0588`, хук 1)** — тем же визитом, после всех роликов
   этого «загрузил»: `python3 agents/analyst/studio_read.py due --channel <канал> --hook upload`.
   Код 1 — прочитать «досмотрели/пролистали» последних N роликов (`studio_read.py plan`),
   записать `studio_read.py record` — порядок и формат прочитанного в
   `agents/analyst/SKILL.md`, «Чтение Studio». Только чтение: ни одного «Изменить» /
   «Оспорить» в Studio. Код 0 — недавнее чтение уже есть, пропустить. Ошибка чтения не
   отменяет итог шага 8.

**Выход 2.0 — 5 роликов подряд без правки полей пользователем.** Счётчик — в журнале: у
каждой Studio-строки `user_edited` (при записи `false`). Пользователь поправил что-то в полях
ролика сам (или попросил поправить после того, как увидел) —
`studio_fields.py edited --slug <slug> --note "что"` (`--video-id` при двух строках одного
имени; `--undo` — отметка была ошибкой); пишет это `upload_records.mark_user_edited`
(журнал по-прежнему пишет только `upload_records.py`). `studio_fields.py streak [--channel]`
печатает текущую серию: Studio-строки по `recorded_at`, с конца до первой правленой;
строки `backfill`/`api` не считаются. 5/5 — условие выхода выполнено.

## Карта модулей и кто их продолжает

| модуль | сейчас (`CF-0421`) | продолжает |
|---|---|---|
| `publisher_config.py` | `.env` → пути секретов, канал, категория; отказ пути внутри git-дерева | — |
| `publisher_auth.py` | installed-app flow, refresh token в файле 600 вне репо; scope аналитики, состояние срока, `status`, вопрос в журнале по флагу (CF-0652), `TokenExpiredError`/`MissingScopeError` (`CF-0589`) | `CF-0016` (канал, аудит проекта), `CF-0020` (`analytics_credentials`), `CF-0591`/`CF-0590` (`NOTIFIERS`) |
| `youtube_client.py` | тонкий адаптер над `googleapiclient` (ленивые импорты), resumable-цикл с повторами | `CF-0018`, `CF-0019` (поиск дублей по каналу) |
| `publish_note.py` | читает готовую заметку `publish/<канал>/<день>/<slug>.md`, проверяет лимиты YouTube и правила `docs/publisher-metadata-rules.md` | пишет её `publish_card.py` (`CF-0017`); читатель остаётся |
| `publish_card.py` | карточка при приёмке: черновик (модель или `--draft`) + сборка по правилам и шаблонам канала + `note_claims` → заметка-карточка со статусом; `place` — рядом с принятым роликом и в ближайший свободный слот (`publish_queue.py`) | `CF-0018` (Studio из полей карточки) |
| `note_claims.py` | название и описание заметки — через разборщик и судью `CF-0553` вместе с текстом ролика; одна правка описания; блок `## Утверждения` (утверждение → цитата → ссылка) с отпечатком | `publish_card.py` зовёт её до выдачи карточки (`CF-0017`) |
| `publish_queue.py` | очередь канала (`CF-0587`): слот из `channels/<канал>.json` → `publisher.slot`, занятые дни из папок дней и `uploads.json`, ближайший свободный, `plan_slot` (приёмка, удержание, окно `CF-0042` и перестановка: `moves`, `warnings`), `apply_moves`, строка о пустом завтрашнем слоте; CLI `show`/`next`/`tomorrow`; пауза канала через `PAUSE_CHECKS` (`CF-0569`) | `CF-0018` (Studio по слоту карточки) |
| `fact_kind.py` | вид ролика запаса по его факту (`CF-0919`): будущее время, дата впереди, свежая дата в названии/описании → `news`, иначе `evergreen`; `judge`, `of_video`, разбор дат словами и цифрами |
| `publish_move.py` | перенос размещённого ролика на другой день и снятие не загруженного в копилку (`CF-0856`), снятие залитого в Studio в запас (`_reserve/`, `CF-0919`; миграция старых — `--migrate-reserve`) и возврат из запаса (`--withdraw`, `return_reserve`, `CF-0918`): `move_plan`/`move_confirm`, пакет одной командой, строка журнала через `upload_records.reschedule`/`withdraw`, один коммит | центр (маршрут API — драйвер центра; `withdraw` центр пока не шлёт) |
| `channel_pause.py` | **единственный писатель и читатель** флага паузы `publish/channel-pauses.json` (`CF-0569`): `set_pause`/`clear_pause` (история не теряется), `status` (paused/expired/free), `gate`/`queue_check` (fail closed); CLI `set`/`clear`/`show` | `CF-0570` (стоп-правило нарушение ставит `--by monitor`), `CF-0018` (зовёт `upload_gate.check_channel_not_paused`) |
| `publish_window.py` | окно паттернов `CF-0042`: K канала, пара ролика (05 → 03 → реестр), лента по слотам, `candidate_check` (в `CANDIDATE_CHECKS`), `record_published` (колонки публикации реестра ротации из `uploads.json`); CLI `check`/`record` | Analyst 2.1 (читает реестр с колонками публикации) |
| `upload_gate.py` | приёмка + пометки + пауза канала (`check_channel_not_paused`, `CF-0569`) + «да» с терминала | `CF-0018` (уведомление о готовности), `CF-0019` (дедуп); окно паттернов `CF-0042` — в `publish_window.py` |
| `upload_records.py` | **единственный писатель и читатель** журнала `publish/uploads.json` (`CF-0586`): формат строки (`check_row`), идемпотентная запись (`record`), дубль `video_id` — ошибка; перенос слота живой строки (`reschedule`, поле `rescheduled`, `CF-0856`); строка API (`source: api`), Studio-строка (`record_studio`, CLI `studio`), `show`/`check` | `CF-0018` (пишет Studio-строку), `CF-0585` (API), `CF-0020`/`CF-0021` (аналитик читает) |
| `studio_fields.py` | Studio-путь (`CF-0018`): `prepare` (JSON полей из готовой карточки, все ворота до расписания), `verify` (перечитанное из Studio против карточки, нормализация), `record` (сверка → `record_studio` → `record_published`), `edited`/`streak` (выход 2.0) | — |
| `backfill_uploads.py` | перенос вышедших и запланированных роликов в журнал из прозы `publish/README.md`, заметок дней и `acceptance-log.json` (`source: backfill`); сухой прогон по умолчанию, `--write`, неразрешённые — списком | повторный прогон на релизе 2.0 против `main` |
| `api_data.py` | API Data по политике YouTube API (`CF-0618`): что считается API Data, отметка отзыва → удаление через 25 дн. (автозапуск в тике и `metrics.py collect`), обновление API-строк журнала через `videos.list` раз в 7 дн., срезание несвежих (28 дн.), `purge --all`/`--channel` по запросу (сухой прогон, `--delete`), `revoke` — отзыв из клиента (`CF-0619`: токен у Google, файл токена и все API Data сразу; сухой прогон, `--yes`), `status` для центра («Токены» → «Данные API») | `CF-0607` (API-путь включён — таймер тика обязателен) |
| `api_switch.py` | переключатель API-загрузки по каналу (`CF-0607`): `schedule/api-upload.json`, единственный писатель `set_switch` (история, `--by user` на включение), `warnings` (Testing, таймер тика, токен), `check` — ворота `upload.py`; CLI `status`/`enable`/`disable` | `CF-0585` (первая боевая загрузка после аудита) |
| `upload.py` | CLI, склейка шагов; за переключателем `api_switch.py`, карточка/слот как у Studio-пути (`CF-0607`) | `CF-0585` |

Зависимости (`google-api-python-client`, `google-auth-oauthlib`,
`google-auth-httplib2`) ставятся в `agents/publisher/.venv`, не глобально;
без них работают `--dry-run` и все тесты (`tests/test_publisher_upload.py`,
моки на уровне `youtube_client`/`publisher_auth`).

Квота (сверено 29.09 по developers.google.com/youtube/v3): у `videos.insert`
с 01.06.2026 своя корзина — 1 ед. за вызов, 100 загрузок в сутки; проверка
канала (`channels.list`) — 1 ед. общей корзины. Проект без аудита грузит только
в `private` навсегда — нужен аудит («Audit and Quota Extension»).

## Аудит YouTube API и Production OAuth-приложения (`CF-0470`)

Порядок шагов пользователя (организация GitHub `example-hd` → сайт бренда
`https://example-hd.github.io` → Search Console → Branding/Data access → Publish app →
`--authorize` заново → демо-видео → форма аудита → `CF-0607`, `CF-0585`), черновики
ответов для Google Auth Platform и формы аудита, сценарий демо-видео и найденные
пробелы соответствия политике YouTube API —
[`docs/api-audit/README.md`](../../docs/api-audit/README.md). Исходники сайта (главная,
privacy policy, terms) — `site/example-hd/`; политика сверена с этим кодом: scopes в
`privacy.html` обязаны совпадать с `publisher_auth.SCOPES`
(`tests/test_example_hd_site.py`), и любая перемена того, что клиент читает, хранит или
кому передаёт, — сначала правка `privacy.html` и `docs/api-audit/`.

### Данные API: отзыв, обновление, удаление (`CF-0618`)

`agents/publisher/api_data.py` — один модуль на всё, что политика требует от хранимых
API Data (толкование — `docs/api-audit/policy-reading.md`):

    python3 agents/publisher/api_data.py status                 # отметка отзыва, API-строки журнала
    python3 agents/publisher/api_data.py purge --all            # сухой прогон удаления по запросу
    python3 agents/publisher/api_data.py purge --channel C --delete
    python3 agents/publisher/api_data.py auto [--delete]        # что удалило бы правило срока
    python3 agents/publisher/api_data.py revoke [--yes]         # отзыв доступа из клиента (CF-0619)

Автозапуск (тик `shared/batch_schedule.py`, начало `metrics.py collect`) удаляет только
должное: API Data через 25 дней после первого `invalid_grant` без нового согласия и
API-поля строк журнала, не обновлённых 28 дней. Удалённая API-строка уходит из `uploads`
в `api_data_deleted` (без id) — `upload_gate.check_not_uploaded` по ней отказывает в
повторной загрузке. Перед «да» `upload_gate.ask_user` показывает `TOS_NOTICE` (ToS 9.1).

`revoke --yes` (`CF-0619`, III.D.2.b, отзыв из клиента) — только по просьбе владельца:
POST токена на `https://oauth2.googleapis.com/revoke` (таймаут `REVOKE_TIMEOUT_S`, токен
нигде не печатается), удаление файла токена, сразу `purge --all`-удаление с причиной
`revoked from the client`, отметка `revoked_from_client_at` в состоянии токена. Google
ответил 400 (`invalid_token`) — локальное удаление всё равно; нет ответа — ничего не
меняется (повторить или отозвать на странице Google). После него загрузка и метрики стоят
до нового `--authorize`.

Кто удалил (`CF-0701`, центр CC-0028). `apply(p, now, extra={"by": "user", "via":
"center"})`, `auto(..., by=, via=)` и `revoke_result(..., by=, via=)` проверяют by/via
(`_who`: нет или непустая строка ≤40 символов в одну строку, иначе `ValueError` до любого
удаления и до запроса к Google) и пишут их в запись `publish/api-data-deletions.jsonl`, в
строки `api_data_deleted` журнала (`api_data_deleted_by` / `_via`) и в состояние токена
(`api_data_deleted.by/via`, `revoked_from_client_by/via`). Автозапуск — `by: "auto"`; без
by/via (CLI `purge`, `revoke`) строка журнала никого не называет — номер задачи
`CF-0618`, который раньше стоял в `api_data_deleted_by`, больше не пишется, старые такие
строки читает `who_deleted(row)` (`task: "CF-0618"`, `by: None`). `revoke_result`
возвращает отзыв данными — `google` (answer/detail), `token` (kind/missing/existed/deleted),
`deletion` (запись журнала удалений), `items`, `ok`/`exit`; `revoke` печатает из него же,
вывод CLI прежний.
