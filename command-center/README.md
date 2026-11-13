# Командный центр Example

Веб-интерфейс фабрики `shorts-content-factory`: каналы, батчи, ролики и приёмка, публикация, статистика, аналитик, вопросы — всё, что умеет фабрика, для человека.

**Status:** the module's own README, kept in its original language. In this snapshot the module lives in `command-center/`; the API it talks to is `core/api/` and the contract is `core/api/openapi.json` (run the type generation with `CC_OPENAPI=../core/api/openapi.json`).

## Стек

Vite + React + TypeScript (strict), Tailwind CSS v4 + shadcn/ui (Radix), TanStack Query, React Router, ESLint + Prettier, Vitest + Testing Library, MSW (подставной API), Playwright.

```
src/
  app/          роутер (13 областей, areas.ts), шапка с табами, тема (theme.ts), QueryClient
  pages/        главная-обзор (overview/), каналы (channels/), батчи (batches/), заглушка «скоро», «нет такой страницы»
  components/ui компоненты shadcn/ui (button, tooltip, alert-dialog — перенесены вручную)
  components/common  общие: тултип, «подробнее», подтверждение, статус-метки, пусто/ошибка/«скоро»
  components/shell   шапка: статус API, переключатель темы
  index.css     тема «Кинозал» (docs/design.md): токены тёмной и светлой, брейкпоинты
  fonts.ts      Oswald, Golos Text, JetBrains Mono из @fontsource (без сети)
  api/          клиент API фабрики: типы из api/openapi.json (npm run api:types), хуки
  mocks/        подставной API (MSW) для тестов: каналы и расписание батчей — с состоянием
  test/         настройка Vitest и хелпер renderApp
tests/e2e/      Playwright: сценарии оболочки + фикстура, блокирующая сеть и ошибки консоли
```

**Тема.** По умолчанию тёмная; светлая — по кнопке в шапке, выбор хранится в `localStorage` этого браузера (`cc-theme`), без хранилища — просто тёмная. `prefers-color-scheme` сознательно не учитывается: тёмная — это вид роликов фабрики (docs/design.md). Атрибут `data-theme` на `<html>`; брейкпоинты макета: `sm` = 640px (телефон до него), `md` = 900px (три колонки с него).

**Правила для экранов.** Номера задач, пути, коммиты — только внутри `<More>` («Подробнее»); подсказки — `<Tip>`; действие с последствиями — `<ConfirmAction>`; блок без API — `<Soon version="0.x">` с объяснением простыми словами.

## Запуск

Нужен Node из `.nvmrc` (`nvm use`; версия также в `package.json → engines`).

```sh
npm ci
npm run dev        # http://127.0.0.1:5173, /api проксируется на CC_API_URL
npm run build      # сборка в dist/ (её раздаёт FastAPI фабрики, CC-0003) + dist/contract.json
npm run api:types  # перегенерировать типы API из контракта фабрики (src/api/README.md)
npm run preview    # собранное приложение на http://127.0.0.1:4173
```

Переменные окружения (при запуске и сборке, можно положить в `.env.local`):

| Переменная            | По умолчанию            | Что делает                                                       |
| --------------------- | ----------------------- | ---------------------------------------------------------------- |
| `CC_API_URL`          | `http://127.0.0.1:8790` | куда dev-сервер и `preview` проксируют `/api`                    |
| `CC_BASE_PATH`        | `/`                     | базовый путь, под которым раздаётся приложение (например `/cc/`) |
| `CC_E2E_PORT`         | `4179`                  | порт сервера, который поднимает Playwright                       |
| `CC_OPENAPI`          | `../api/openapi.json` (here: `../core/api/openapi.json`) | контракт API для `api:types` и сверки; `off` — не сверять        |
| `CC_OPENAPI_REQUIRED` | —                       | `1` — отсутствие контракта при сверке становится ошибкой         |
| `CC_TEST_WORKERS`     | половина ядер           | воркеры Vitest и Playwright (см. «Тесты на занятой машине»)      |

В собранном приложении API всегда на том же origin: клиент ходит на `<base>api/…`.

## Проверки

```sh
npm run lint       # ESLint + Prettier --check  (npm run format — поправить формат)
npm run typecheck  # api:check (типы не отстали от контракта) + tsc -b
npm run test       # Vitest (jsdom + MSW)
npm run e2e        # Playwright: сборка + vite preview + сценарии в Chromium (подставной API)
```

Иконка центра — `public/favicon.svg` (и упрощённый `favicon-16.svg` для 16 px); после их правки `npm run favicon` (`scripts/favicon.ts`, Chromium из Playwright) пересобирает `favicon-32.png`, `apple-touch-icon.png` и `favicon.ico`.

Тесты никогда не ходят в сеть. В Vitest любой запрос мимо обработчиков из `src/mocks/handlers.ts` — ошибка (`onUnhandledRequest: 'error'`). В Playwright фикстура `tests/e2e/fixtures.ts` подменяет `/api/*` и обрывает всё, что идёт не на локальный сервер; оборванный запрос роняет тест.

`typecheck` и `build` падают, если `api/openapi.json` фабрики поменялся, а типы не перегенерировали (`npm run api:types`). Нет контракта рядом (CI, без фабрики) — предупреждение, сверка только с закоммиченным снимком; подробно — `src/api/README.md`.

Перед первым `npm run e2e` поставьте браузер: `npx playwright install chromium`. Тяжёлый Playwright не запускайте, пока у фабрики идёт батч (`scripts/runlog batch-active` в корне фабрики).

### Тесты на занятой машине

Центр гоняют рядом с полным прогоном фабрики (load 60–110), поэтому потолки ожиданий выше штатных, но конечны — зависший тест всё равно падает:

| Что                                  | Значение  | Где                                     |
| ------------------------------------ | --------- | --------------------------------------- |
| Vitest `testTimeout` / `hookTimeout` | 20 с      | `src/test/timeouts.ts` → vite.config.ts |
| `findBy*` / `waitFor` (RTL)          | 10 с      | `src/test/timeouts.ts` → setup.ts       |
| Playwright: тест / `expect`          | 60 / 10 с | `playwright.config.ts`                  |

Явные `{ timeout }` в `findBy*` не нужны — общего потолка хватает. Параллельность Vitest (`maxWorkers`) и Playwright (`workers`) — половина ядер; `CC_TEST_WORKERS=<n>` задаёт число явно (в CI Playwright без переменной по-прежнему в 1 воркер):

```sh
CC_TEST_WORKERS=2 npm test
CC_TEST_WORKERS=1 npm run e2e
```

Проверить устойчивость — прогнать 3 раза подряд под искусственной нагрузкой (`yes > /dev/null` × число ядер; нагрузка снимается и при падении, и по Ctrl-C; при открытом батче фабрики скрипт ничего не нагружает и выходит с кодом 3):

```sh
CC_OPENAPI=off scripts/under-load.sh -- npm test
CC_OPENAPI=off scripts/under-load.sh -- npm run e2e
scripts/under-load.sh -n 24 -r 5 -- npm test   # 24 нагрузчика, 5 прогонов
```

В конце — итог «N/3 зелёных» и load average до/после каждого прогона.

Version history is in `CHANGELOG.md`; what comes next is in `ROADMAP.md`.
