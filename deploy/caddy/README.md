# Caddy — crown.skykraft.su

Приложение слушает **`127.0.0.1:8090`** (`docker-compose.yml`).

```bash
sudo cp deploy/caddy/crown.conf /etc/caddy/sites/crown.conf
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Проверка:

```bash
curl -sS https://crown.skykraft.su/api/health
```
