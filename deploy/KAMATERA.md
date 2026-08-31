# Запуск на Kamatera: бот + веб-панель, доступ через SSH-туннель

Пошагово, под конкретный сценарий:

- **Бот и панель вместе** — один процесс `web/api.py` (он же торгует).
- **Домена нет** → наружу не смотрит ничего, панель открывается через SSH-туннель.
- **Код через приватный GitHub**, секреты — отдельно по `scp`.

> ## ⚠️ Не запускайте `tm-steambot.service` и `tm-steambot-web.service` вместе
>
> `server_runner.py` и `web/api.py` **каждый** поднимает свой `ServerOrchestrator`
> и торгует самостоятельно. Два включённых сервиса = два бота на одних аккаунтах:
> дублирующиеся ордера, гонки за баланс, лимиты Steam и реальная потеря денег.
>
> В этой инструкции работает **только `tm-steambot-web.service`**.
> `tm-steambot.service` нужен, если панель не используется вовсе.

---

## 0. Перед всем — ротация ключей

Пройдите [ROTATION.md](ROTATION.md). Пароли прокси лежали в логах, `.env`
уезжал в сборки, проект синхронизирован в OneDrive. Ставить на публичный сервер
креды, которые могли утечь, — значит отдать их вместе с сервером.

---

## 1. Создание сервера в Kamatera

В панели Kamatera → **Create Server**:

| Параметр | Значение | Почему |
|---|---|---|
| Image | **Ubuntu Server 24.04 LTS 64-bit** | свежий Python 3.12, долгая поддержка |
| Type | General Purpose | торговый бот не нагружает CPU |
| CPU | 1-2 vCPU | бот I/O-bound; на 1 vCPU дольше только разовая сборка фронта |
| RAM | **2 GB** | замерено, расклад ниже |
| Storage | 20 GB SSD | venv ~600 МБ + node_modules ~560 МБ + логи |
| Networking | оставьте **Public IP** | нужен для SSH; наружу мы всё равно закроемся фаерволом |
| Location | ЕС (Amsterdam/Frankfurt) | ближе к Steam/CSGO.TM, меньше подозрений чем экзотика |

**Почему 2 ГБ, а не 4.** Раньше здесь стояло 4 ГБ с обоснованием «`next build` на
2 ГБ падает по OOM». Проверили — не падает. Замеры на этом проекте:

| что | память |
|---|---|
| бот + FastAPI (`tm-steambot-web`, один процесс) | ~250-350 МБ |
| пик сканера поверх этого | +23 МБ |
| `next start` с готовой сборкой | ~100-150 МБ |
| `next build` — разовая операция | пик ~330 МБ, проходит с `--max-old-space-size=1400` |

В работе 24/7 выходит ~500 МБ. Настоящей причиной запаса был сканер: он тянул
прайс-лист CSGO.TM (~220 МБ JSON) целиком через `json.loads` и давал пик **845 МБ**
на каждом скане. После перехода на потоковый разбор (`ijson`) пик — **23 МБ**,
и 4 ГБ стали не нужны.

**Password/SSH Key:** выберите **SSH Key** и вставьте свой публичный ключ.
Если ключа нет, на своей машине (PowerShell):

```powershell
ssh-keygen -t ed25519 -C "tm-steambot"
type $env:USERPROFILE\.ssh\id_ed25519.pub    # это вставить в Kamatera
```

Пароль вместо ключа — плохая идея: сервер с торговым ботом брутфорсят с первого часа.

---

## 2. Первый вход и базовая защита

```bash
ssh root@<IP-СЕРВЕРА>

# Обновление
apt update && apt upgrade -y

# Пользователь под бота (без root)
adduser --disabled-password --gecos "" botuser

# Фаервол: наружу открыт ТОЛЬКО SSH.
# Панель (8000) и фронт (3002) слушают localhost и доступны через туннель.
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
ufw status

# Защита от брутфорса SSH
apt install -y fail2ban
systemctl enable --now fail2ban
```

Отключите вход по паролю (если заходите по ключу):

```bash
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart ssh
```

---

## 3. Пакеты

```bash
apt install -y python3 python3-venv python3-pip git curl

# Node 20 LTS (в репозитории Ubuntu слишком старый для Next 15)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

python3 --version    # ждём 3.12.x
node --version       # ждём v20.x
```

---

## 4. Приватный репозиторий (на вашей машине)

`.gitignore` уже проверен: код попадает, секреты — нет.

```powershell
cd "C:\Users\vania\OneDrive\Desktop\tm-steambot-feature-proxy-rotation-and-cleanup 2"

git init
git add -A
```

**Обязательно проверьте, что секретов нет в индексе:**

```powershell
git status --short
git ls-files | Select-String -Pattern '\.env$|maFile|accounts\.json|proxies\.txt|bot_config\.json|\.db$'
```

Вторая команда должна вернуть **пусто**. Если что-то нашлось — не коммитьте, скажите мне.

```powershell
git commit -m "TM Steam Bot"
# Создайте ПРИВАТНЫЙ репозиторий на github.com, затем:
git remote add origin git@github.com:ВАШ_ЛОГИН/tm-steambot.git
git branch -M main
git push -u origin main
```

> Репозиторий именно **приватный**. Даже без секретов код раскрывает вашу
> торговую логику и структуру.

### Доступ с сервера

```bash
sudo -u botuser -H bash
ssh-keygen -t ed25519 -C "server-deploy" -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Вывод добавьте на GitHub: **Repo → Settings → Deploy keys → Add deploy key**
(read-only, без write access).

---

## 5. Клонирование и секреты

```bash
# от root
mkdir -p /opt/tm-steambot
chown botuser:botuser /opt/tm-steambot

sudo -u botuser -H bash
git clone git@github.com:ВАШ_ЛОГИН/tm-steambot.git /opt/tm-steambot
exit
```

Теперь **со своей машины** копируем то, чего в git нет:

```powershell
cd "C:\Users\vania\OneDrive\Desktop\tm-steambot-feature-proxy-rotation-and-cleanup 2"

scp .env accounts.json proxies.txt bot_config.json root@<IP>:/tmp/
scp *.maFile root@<IP>:/tmp/
```

> `bot_config.json` не в git (он в `.gitignore`), но серверу **нужен**: без него
> подхватятся дефолты, а у вас там свои пороги — например `min_profit_pct = -5.5`.
> Скопируйте обязательно, иначе бот будет торговать по другим правилам.

На сервере раскладываем и закрываем права:

```bash
mv /tmp/.env /tmp/accounts.json /tmp/proxies.txt /tmp/bot_config.json /opt/tm-steambot/
mv /tmp/*.maFile /opt/tm-steambot/ 2>/dev/null

cd /opt/tm-steambot
chown -R botuser:botuser /opt/tm-steambot
chmod 600 .env accounts.json proxies.txt bot_config.json
chmod 600 *.maFile 2>/dev/null
mkdir -p data logs && chmod 700 data logs
chown -R botuser:botuser data logs

ls -l .env accounts.json proxies.txt *.maFile   # везде -rw-------
```

---

## 6. Python-окружение

```bash
sudo -u botuser -H bash
cd /opt/tm-steambot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

---

## 7. Проверка ДО включения торговли

```bash
cd /opt/tm-steambot
.venv/bin/python server_runner.py --dry-run
```

Ждём: логин всех аккаунтов, балансы Steam и CSGO.TM, `access_token: OK`,
`sell-статус: OK`. **Сделок не будет** — это только проверка.

Если логин не проходит — почти всегда одно из трёх:
- прокси из `accounts.json` не отвечает с этого IP;
- Steam требует подтверждение с нового устройства (проверьте почту);
- не доехал `.maFile` или права на нём не 600.

Разберитесь здесь — дальше не идите, пока dry-run не чистый.

---

## 8. Пароль панели

```bash
cd /opt/tm-steambot
.venv/bin/python -m web.hashpw
```

Введите пароль (от 12 символов), получите строку `scrypt$...`. Дальше от root:

```bash
mkdir -p /etc/tm-steambot
cat > /etc/tm-steambot/web.env <<'EOF'
WEB_API_PASSWORD_HASH=scrypt$32768$8$1$ВСТАВЬТЕ_СВОЁ
WEB_CORS_ORIGINS=http://localhost:3002
EOF

chmod 600 /etc/tm-steambot/web.env
chown botuser:botuser /etc/tm-steambot/web.env
```

> `WEB_TRUST_PROXY` **не ставим** — nginx нет, доверять `X-Forwarded-For`
> в этой схеме нельзя.

---

## 9. Сборка фронтенда

```bash
sudo -u botuser -H bash
cd /opt/tm-steambot/web/frontend
npm ci
npm run build
exit
```

`npm ci` требует `package-lock.json` — он в репозитории есть. На 2 ГБ сборка
проходит штатно (пик ~330 МБ). Своп всё равно стоит завести — как страховку
на случай, если фронт со временем разрастётся:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## 10. Службы

```bash
cd /opt/tm-steambot
cp deploy/tm-steambot-web.service /etc/systemd/system/
cp deploy/tm-steambot-frontend.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now tm-steambot-web
systemctl enable --now tm-steambot-frontend

systemctl status tm-steambot-web --no-pager
systemctl status tm-steambot-frontend --no-pager
```

**Проверьте, что наружу ничего не смотрит:**

```bash
ss -tlnp | grep -E '8000|3002'
```

В обеих строках должно быть `127.0.0.1:8000` и `127.0.0.1:3002`.
Если увидели `0.0.0.0` — останавливайте службу и разбирайтесь, панель
торчит в интернет.

> ⚠️ `tm-steambot.service` (headless-бот) **не включаем** — см. предупреждение
> в начале. Если он был включён раньше:
> `systemctl disable --now tm-steambot`

---

## 11. Ротация логов

```bash
cp /opt/tm-steambot/deploy/logrotate-tm-steambot /etc/logrotate.d/tm-steambot
logrotate --debug /etc/logrotate.d/tm-steambot
```

---

## 12. Заход в панель

**Со своей машины** (не на сервере) поднимаем туннель:

```powershell
ssh -N -L 3002:127.0.0.1:3002 -L 8000:127.0.0.1:8000 root@<IP-СЕРВЕРА>
```

Окно не закрывайте — пока оно живёт, работает туннель. Открывайте:

```
http://localhost:3002
```

Введите пароль из шага 8. Трафик шифруется SSH, в интернете панель не видна.

Для удобства добавьте в `~/.ssh/config` на своей машине:

```
Host tmbot
    HostName <IP-СЕРВЕРА>
    User root
    LocalForward 3002 127.0.0.1:3002
    LocalForward 8000 127.0.0.1:8000
```

Тогда достаточно `ssh -N tmbot`.

---

## 13. Ежедневная эксплуатация

```bash
# Логи панели и торговли
journalctl -u tm-steambot-web -f
tail -f /opt/tm-steambot/logs/bot.log

# Перезапуск
systemctl restart tm-steambot-web

# Остановить торговлю, оставив панель:
#   в /etc/tm-steambot/web.env добавьте WEB_AUTOSTART=0 и перезапустите
```

### Обновление кода

```powershell
# у себя
git add -A && git commit -m "правки" && git push
```

```bash
# на сервере
sudo -u botuser -H bash -c 'cd /opt/tm-steambot && git pull'
# если менялся фронт:
sudo -u botuser -H bash -c 'cd /opt/tm-steambot/web/frontend && npm ci && npm run build'
systemctl restart tm-steambot-web tm-steambot-frontend
```

Секреты `git pull` не трогает — они не в репозитории.

---

## 14. Когда захотите домен и HTTPS

Тогда пригодится [nginx-tm-steambot.conf](nginx-tm-steambot.conf):

1. Купить домен, A-запись на IP сервера.
2. `apt install -y nginx certbot python3-certbot-nginx`
3. Скопировать конфиг, заменить `bot.example.com` на свой домен.
4. `certbot --nginx -d ваш-домен`
5. `ufw allow 'Nginx Full'`
6. В `/etc/tm-steambot/web.env` добавить `WEB_TRUST_PROXY=1`
   и `WEB_CORS_ORIGINS=https://ваш-домен`, перезапустить службы.

Туннель после этого не нужен — но и порты 8000/3002 наружу открывать
по-прежнему не надо, nginx ходит к ним по localhost.

---

## Быстрый чеклист

- [ ] Ключи ротированы ([ROTATION.md](ROTATION.md))
- [ ] `ufw` включён, снаружи открыт только SSH
- [ ] Вход по SSH-ключу, пароль отключён
- [ ] `git ls-files` не показывает секретов
- [ ] `.env`, `accounts.json`, `proxies.txt`, `*.maFile` — режим 600
- [ ] `bot_config.json` скопирован (иначе другие пороги торговли)
- [ ] `--dry-run` проходит чисто
- [ ] `ss -tlnp` показывает только `127.0.0.1` для 8000 и 3002
- [ ] `tm-steambot.service` выключен (работает только `-web`)
- [ ] Вход в панель через туннель работает
