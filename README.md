# Crown

Шлюз для разбора тендерной PDF-документации. В одном сервисе собраны **задания 1, 8 и 9**: суммаризация извещения через Gemini, API-ключ с лимитом 5 запросов в минуту и выкладка в Docker (FastAPI + PostgreSQL + Redis) с CI.

Сервис: [https://crown.skykraft.su](https://crown.skykraft.su)

| | |
|--|--|
| Домен | `crown.skykraft.su` |
| Стек | FastAPI · PostgreSQL · Redis · Gemini |
| Лимит | 5 запросов к ИИ в минуту на ключ |
| Cookie | `crown_api_key`, **httpOnly** |

Подробности по алгоритму — в [SOLUTION.md](SOLUTION.md).

## Что делает

1. Выдаёт тестовый API-ключ (`POST /api/keys`) и кладёт его в httpOnly cookie. Без ключа защищённые методы отвечают 401.
2. Принимает PDF с госзакупок, проверяет лимит в Redis, гоняет файл в Gemini.
3. Возвращает выжимку: сумма контракта, сроки, требования к исполнителю, штрафы.

## Переменные окружения

См. `.env.example`. Нужное:

| Переменная | Назначение |
|------------|------------|
| `API_GEMINI` | ключ Google Gemini |
| `GEMINI_MODEL` / `GEMINI_MODELS` | основная модель и цепочка failover при 429 |
| `AI_PROXY_URL` | SOCKS/HTTP для выхода к Google |
| `COOKIE_SECURE` | `true` за HTTPS |
| `RATE_LIMIT_REQUESTS` | по умолчанию 5 |
| `DATABASE_URL` / `REDIS_URL` | в compose проставляются сами |

Секреты в git не кладём.

## API

| Метод | Путь | Ключ | Зачем |
|-------|------|------|--------|
| `GET` | `/api/health` | нет | postgres + redis + флаг Gemini |
| `POST` | `/api/keys` | нет | выдать ключ, Set-Cookie |
| `GET` | `/api/keys/me` | да | префикс и остаток квоты |
| `POST` | `/api/keys/revoke` | да | отозвать, сбросить cookie |
| `POST` | `/api/summarize` | да | PDF → выжимка |
| `GET` | `/api/history` | да | последние разборы этого ключа |

Браузер с `Accept: text/html` получает страницы, в том числе 401/404/429/5xx. `curl` с `Accept: application/json` — JSON.

## Разработка

Миграции: `alembic upgrade head` (compose делает это на старте контейнера).

## Типовые сбои

- **503 на /api/summarize** — пустой `API_GMINI` или Gemini недоступен. Health при этом может быть `ok`, если живы Postgres и Redis.
- **502** — модель ответила ошибкой; в логах контейнера `app` будет HTTP-код Gemini (без ключа).
- **429** — 6-й запрос за минуту. `Retry-After` в заголовке.
- **401** — нет cookie. `POST /api/keys`.
- **Gemini 429 на всех моделях** — кончилась квота Google, не наш лимит. Смотрите `GEMINI_MODELS`.
- **Таймаут на больших PDF** — Caddy и приложение ждут до 180 с; файл больше **50 МБ** отсекается на входе (и Caddy, и FastAPI).

## Лицензия

MIT, см. [LICENSE](LICENSE).
