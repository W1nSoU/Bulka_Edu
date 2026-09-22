# Bulka Edu — Розгортання (Deployment Guide)

## 1. Запуск через Docker Compose (Рекомендовано)

### 1.1 Клонування та налаштування оточення
```bash
git clone <repo_url>
cd Bulka_Edu

# Створити .env файл на основі шаблону
cp .env.example .env
nano .env
```

Обов'язкові змінні в `.env`:
```ini
BOT_API_TOKEN=your_bot_token_from_botfather
DEV_CHAT_ID=-100xxxxxxxxxx
MAIN_DEVELOPER_ID=123456789
GROQ_API_KEY=gsk_...
DAYS_TOTAL=5
DEBUG=false
LOG_TO_FILE=true
```

### 1.2 Запуск контейнера
```bash
# Побудова та фоновий запуск
docker compose up -d --build

# Перегляд логів
docker compose logs -f bot
```

---

## 2. Запуск напряму через Python / systemd

### 2.1 Встановлення залежностей
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2.2 Запуск
```bash
python3 main.py
```

### 2.3 Systemd Unit (`/etc/systemd/system/bulka-bot.service`)
```ini
[Unit]
Description=Bulka Edu Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=/opt/bulka
EnvironmentFile=/opt/bulka/.env
ExecStart=/opt/bulka/venv/bin/python3 /opt/bulka/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bulka-bot
sudo journalctl -u bulka-bot -f
```

---

## 3. Деплой глобальної версії v2 на бойовому сервері (Systemd)

### Крок 1. Зупинити бота на сервері
```bash
sudo systemctl stop bulka-edu || sudo pkill -f "python.*main.py"
```

### Крок 2. Оновити код із репозиторію
```bash
cd /home/admin1/Bulka_Edu
git pull
```

### Крок 3. Оновити залежності у віртуальному середовищі
```bash
/home/admin1/Bulka_Edu/venv/bin/pip install -r requirements.txt
```

### Крок 4. Скопіювати нові зображення (якщо змінювалися або додавалися)
```bash
scp -r ./img admin1@46.63.xx.xx:/home/admin1/Bulka_Edu/
```

### Крок 5. Запустити міграційний скрипт (зробить автоматичний бекап всіх БД)
```bash
sudo /home/admin1/Bulka_Edu/venv/bin/python3 /home/admin1/Bulka_Edu/scripts/migrate_server.py
```

### Крок 6. Запустити бота та перевірити статус і логи
```bash
sudo systemctl start bulka-edu
sudo journalctl -u bulka-edu -f -n 50
```

---

## 4. Відкат (Rollback) — якщо щось пішло не так

### Варіант А. Автоматичний відкат баз даних (рекомендовано)
```bash
# 1. Зупинити бота
sudo systemctl stop bulka-edu

# 2. Відновити останній бекап
sudo /home/admin1/Bulka_Edu/venv/bin/python3 /home/admin1/Bulka_Edu/scripts/rollback_server.py --latest

# 3. (За потреби) Відкотити код у Git до попереднього коміту
git reset --hard HEAD~1

# 4. Запустити бота
sudo systemctl start bulka-edu
```

### Варіант Б. Ручне відновлення з папки backups/
```bash
sudo systemctl stop bulka-edu
# Подивитися список доступних бекапів
ls -la /home/admin1/Bulka_Edu/backups/

# Скопіювати потрібний бекап назад у database/
cp /home/admin1/Bulka_Edu/backups/backup_РРРРММДД_ГГХХСС/*.db /home/admin1/Bulka_Edu/database/

# Запустити бота
sudo systemctl start bulka-edu
```

