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
