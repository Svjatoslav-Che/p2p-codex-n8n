# Automation Workbench

Локальный переносимый проект:

```text
Codex orchestrator -> Codex Browser/local tools -> reports -> n8n gate
```

В Git хранятся код adapter, workflow JSON, сценарии, материалы и выбранные
evidence. База n8n, credentials, cookies, логи и массовые screenshots остаются
внутри проекта под `.runtime/`, но не попадают в Git.

## Структура

```text
automation-workbench/
├── adapter/                 # локальный HTTP adapter для Codex
├── workflows/               # экспортируемые workflow n8n
├── scenarios/
│   └── website-availability/
│       ├── SCENARIO.md
│       ├── sites.json
│       ├── materials/
│       └── runs/            # локальные результаты, ignored
├── evidence/                # выбранные результаты для Git
├── scripts/
├── .runtime/                # n8n DB/logs/files, ignored
├── AGENTS.md                # правила для Codex
└── docker-compose.yml
```

## Развёртывание после clone

На машине нужны Docker Desktop, Python 3, Codex и Google Chrome.

```bash
make bootstrap
make start
```

После первого чистого запуска:

1. открыть `http://127.0.0.1:5678`;
2. пройти локальный setup owner;
3. выполнить `make import-workflows`;
4. опубликовать нужные workflows в n8n.

На машине с уже перенесённым `.runtime/n8n` owner и workflows сохраняются.

## Обычная работа

```bash
make start
make status
make check
make stop
```

Для основной модели `Codex -> Browser -> n8n` adapter не требуется. Он оставлен
для будущих workflow, где n8n сам инициирует coding-задачу. При необходимости
он запускается в foreground отдельной командой:

```bash
make adapter
```

Так проект не создаёт launch agents, глобальные конфиги или фоновые файлы вне
своей папки.

Workflow definitions:

```bash
make import-workflows
make export-workflows
```

## Запуск сценария проверки сайтов

1. Заполнить `scenarios/website-availability/sites.json`.
2. Передать Codex текст из
   `scenarios/website-availability/RUN_PROMPT.md`.
3. Codex создаст изолированную папку запуска, проверит URL, сохранит PNG и
   отчёты, затем отправит итог в n8n.
4. n8n вернёт разрешение на функциональные проверки только при полном PASS.

На холсте n8n можно держать много веток, но для переиспользования и понятной
истории лучше хранить крупные сценарии отдельными workflow JSON и связывать их
через webhooks/sub-workflows.

## Git и доказательства

Raw run directories не коммитятся, иначе PNG быстро раздуют репозиторий.
Выбранный результат переносится в:

```text
evidence/<scenario>/<run-id>/
```

После этого его можно добавить обычным `git add`. Секреты и runtime всегда
остаются исключёнными.

Для переноса выбранного запуска:

```bash
make evidence RUN=<run-id>
git add evidence/website-availability/<run-id>
git commit -m "Add website availability evidence <run-id>"
git push
```

Команда отказывается перезаписывать уже сохранённый evidence. Git remote
настраивается один раз после создания репозитория на GitHub/GitLab; сам проект
не хранит токены или пароль от remote.
