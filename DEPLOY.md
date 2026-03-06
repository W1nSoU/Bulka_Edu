# Bulka Edu — Deployment Guide

## Структура розгортання

```
Developer server         Client server
──────────────           ──────────────
verify-api  ←── HTTPS ─── bot (main.py)
master-bot               (license locked to hardware)
```

---

## 1. Швидкий старт (Docker Compose)

### 1.1 Клонувати та налаштувати

```bash
git clone <repo> bulka_edu && cd bulka_edu

# Серверний .env (verify-api + master-bot)
cp private_server/.env.example private_server/.env
nano private_server/.env   # заповнити: API_SECRET_KEY, MASTER_BOT_TOKEN тощо

# Кореневий .env (bot)
cp .env.example .env
nano .env                  # BOT_API_TOKEN, DEV_CHAT_ID, LICENSE_VERIFY_URL
```

### 1.2 Обов'язкові ENV змінні

| Змінна | Де використовується | Опис |
|--------|---------------------|------|
| `HARDWARE_ID_OVERRIDE` | bot, verify-api | Унікальний рядок-ідентифікатор сервера (замість фізичного hardware) |
| `BOT_API_TOKEN` | bot | Telegram Bot API token |
| `MASTER_BOT_TOKEN` | master-bot, verify-api | Token адмін-бота |
| `MASTER_CHAT_ID` | master-bot, verify-api | Telegram ID для алертів |
| `MASTER_ALLOWED_IDS` | master-bot | Telegram ID адмінів (через кому) |
| `API_SECRET_KEY` | verify-api, bot | Спільний секрет для X-API-Key |
| `LICENSE_VERIFY_URL` | bot | URL verify-api сервера |

> **HARDWARE_ID_OVERRIDE** — критично для Docker.
> Встановіть унікальний стабільний рядок для кожного сервера-клієнта:
> ```
> HARDWARE_ID_OVERRIDE=ClientCompanyA-Prod-Server-2024
> ```

### 1.3 Збірка образу

```bash
docker-compose build
```

### 1.4 Запуск серверної частини (на сервері розробника)

```bash
# Спочатку verify-api (інші чекають його healthcheck)
docker-compose up -d verify-api

# Потім master-bot
docker-compose up -d master-bot

# Перевірка
docker-compose logs -f verify-api
curl http://localhost:8443/api/health
```

### 1.5 Перша активація ліцензії (на сервері клієнта)

```bash
# 1. Згенерувати ключ через master-bot або CLI:
docker-compose run --rm verify-api \
  python3 -m security_functions.master_key generate "CompanyA"

# Або через Telegram: /generate → "CompanyA"

# 2. Прив'язати ключ до залізного профілю клієнтського сервера:
SECURITY_DATA_DIR=/opt/bulka/security \
HARDWARE_ID_OVERRIDE=CompanyA-Prod-Server \
  python3 -m security_functions.key_store activate "XXXX-XXXX-XXXX-XXXX"

# 3. Snapshot security files в .chksum:
python3 security_functions/_seal.py
```

### 1.6 Запуск бота (на сервері клієнта)

```bash
# Volume: смонтувати директорію з security data
docker run -d \
  --name bulka-bot \
  --env-file .env \
  -e HARDWARE_ID_OVERRIDE=CompanyA-Prod-Server \
  -e SECURITY_DATA_DIR=/security \
  -v /opt/bulka/security:/security \
  bulka-edu:latest \
  python3 main.py
```

---

## 2. Volume Mounting — деталі

### Які файли ОБОВ'ЯЗКОВО монтувати

```
/app/security_data/
  .license          ← зашифрований ліцензійний ключ
  .salt             ← PBKDF2 сіль
  .master_secret    ← AES ключ шифрування (тільки на dev-сервері)
  .chksum           ← хеші для integrity checks
  master_keys.db    ← база ключів (тільки на dev-сервері)
  guard.log         ← лог безпеки

/app/private_server/data/
  activation_log.db ← журнал активацій (тільки на dev-сервері)
```

### Docker named volumes

```bash
# Переглянути вміст volume
docker run --rm -v bulka-security-data:/data alpine ls -la /data

# Скопіювати файл у volume
docker cp .license bulka-verify-api:/app/security_data/.license

# Резервна копія volume
docker run --rm \
  -v bulka-security-data:/data \
  -v $(pwd)/backup:/backup \
  alpine tar czf /backup/security_$(date +%Y%m%d).tar.gz -C /data .
```

---

## 3. Оновлення хешів після зміни коду

```bash
# Після БУДЬ-ЯКОЇ зміни security_functions/*.py:
python3 security_functions/_seal.py

# Перебудувати образ і перезапустити
docker-compose build
docker-compose up -d --no-deps verify-api bot master-bot
```

---

## 4. Компіляція PyInstaller

### 4.1 Встановлення

```bash
pip install pyinstaller
```

### 4.2 Збірка (one-dir режим)

```bash
pyinstaller bulka_edu.spec

# Результат:
# dist/bulka_edu/bulka_edu   ← виконуваний файл
# dist/bulka_edu/             ← папка з усіма залежностями
```

### 4.3 Розгортання скомпільованого файлу

```bash
# Скопіювати на сервер клієнта
scp -r dist/bulka_edu/ user@client-server:/opt/bulka/

# Активувати ліцензію (перший запуск)
cd /opt/bulka/bulka_edu
SECURITY_DATA_DIR=/opt/bulka/security \
HARDWARE_ID_OVERRIDE=CompanyA-Server \
  ./bulka_edu --activate XXXX-XXXX-XXXX-XXXX   # через key_store CLI

# Запуск
SECURITY_DATA_DIR=/opt/bulka/security \
HARDWARE_ID_OVERRIDE=CompanyA-Server \
LICENSE_VERIFY_URL=https://dev-server.com:8443/api/verify \
BOT_API_TOKEN=... \
  ./bulka_edu
```

### 4.4 Як працює integrity у скомпільованому файлі

| Перевірка | Normal .py | PyInstaller frozen |
|-----------|-----------|-------------------|
| `_SM` (хеші .py файлів) | ✅ активна | ⏭ пропускається (`_FROZEN=True`) |
| `.chksum` (data files) | ✅ активна | ✅ активна |
| hardware_id | ✅ активна | ✅ активна (`HARDWARE_ID_OVERRIDE`) |
| server verify | ✅ активна | ✅ активна |
| self-destruct | ✅ активна | ✅ активна |

---

## 5. Запуск FastAPI і master-bot окремо

### FastAPI verify-api

```bash
# Development
python3 -m uvicorn private_server.app:app \
  --host 0.0.0.0 --port 8443 --reload

# Production з SSL
python3 -m uvicorn private_server.app:app \
  --host 0.0.0.0 --port 8443 \
  --ssl-certfile /etc/ssl/certs/cert.pem \
  --ssl-keyfile  /etc/ssl/private/key.pem

# Перевірка
curl https://your-server.com:8443/api/health
curl https://your-server.com:8443/api/status \
  -H "X-API-Key: YOUR_API_SECRET_KEY"
```

### Master-bot

```bash
python3 private_server/master_bot.py

# systemd service (рекомендовано)
sudo cp deploy/bulka-master-bot.service /etc/systemd/system/
sudo systemctl enable --now bulka-master-bot
```

---

## 6. Systemd сервіси (production)

```ini
# /etc/systemd/system/bulka-verify-api.service
[Unit]
Description=Bulka Edu Verify API
After=network.target

[Service]
User=bulka
WorkingDirectory=/opt/bulka
EnvironmentFile=/opt/bulka/.env
ExecStart=/opt/bulka/venv/bin/uvicorn private_server.app:app \
          --host 0.0.0.0 --port 8443
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 7. Checklist першого розгортання

```
[ ] Заповнити всі ENV в .env та private_server/.env
[ ] Встановити HARDWARE_ID_OVERRIDE (унікальний на кожному сервері)
[ ] python3 security_functions/_seal.py  (запечатати хеші)
[ ] Згенерувати Master Key: /generate у Telegram або CLI
[ ] Активувати ліцензію: python3 -m security_functions.key_store activate KEY
[ ] Запустити verify-api: docker-compose up -d verify-api
[ ] Перевірити healthcheck: curl .../api/health
[ ] Запустити bot: docker-compose up -d bot
[ ] Запустити master-bot: docker-compose up -d master-bot
[ ] Перевірити /api/status через master-bot /status
```

---

## 8. PyInstaller збірка

### Підготовка

```bash
pip install pyinstaller
python3 security_functions/_seal.py   # запечатати перед збіркою!
```

### One-directory bundle (рекомендовано)

```bash
bash build/build.sh
# Результат: dist/bulka_edu/bulka_edu
```

### Single-file EXE

```bash
bash build/build.sh --onefile
# Результат: dist/bulka_edu
```

### Запуск зібраного файлу

```bash
# Скопіювати .license, .salt, .master_secret, .chksum поруч із EXE
cp security_functions/.license       dist/security_functions/.license
cp security_functions/.salt          dist/security_functions/.salt
cp security_functions/.master_secret dist/security_functions/.master_secret
cp security_functions/.chksum        dist/security_functions/.chksum

# Запуск
HARDWARE_ID_OVERRIDE=my-stable-key \
LICENSE_VERIFY_URL=https://server:8443/api/verify \
./dist/bulka_edu/bulka_edu
```

> ⚠️  В frozen-режимі (PyInstaller) перевірка хешів `.py`-файлів пропускається
> автоматично (`_FROZEN = True`). Перевірки `.license`, `.salt`, `.master_secret`
> та `hardware_id` залишаються активними.

---

## 9. Docker + Volume — деталі монтування

```yaml
# Bot бачить ліцензійні файли через bind-mount:
volumes:
  - ./deploy/data/.license:/app/security_functions/.license:rw
  - ./deploy/data/.salt:/app/security_functions/.salt:rw
  - ./deploy/data/.master_secret:/app/security_functions/.master_secret:rw
  - ./deploy/data/.chksum:/app/security_functions/.chksum:rw
```

**Стабільний hardware_id у Docker** (без фізичного MAC/CPU/Disk):
```bash
# Генерація унікального HARDWARE_ID_OVERRIDE (один раз!)
python3 -c "import secrets; print(secrets.token_hex(16))"
# Записати в .env:
HARDWARE_ID_OVERRIDE=<generated_value>
```

> ⚠️  Зміна `HARDWARE_ID_OVERRIDE` = зміна hardware профілю = бот заблокується.
