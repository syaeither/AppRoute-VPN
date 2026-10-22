# Эксплуатация и диагностика

Все команды `python3 -m approute` выполнять из корня проекта. Управление сетью требует sudo. Действительный конфиг хранить вне проекта.

## Подготовка (Debian/Ubuntu)

```bash
sudo apt install iproute2 wireguard-tools util-linux
python3 --version
python3 -m approute --help
```

Нужен Python 3.10+ и поддержка WireGuard в Linux. В конфиге обязательны Address и DNS в Interface; ключи и peer должны быть действительными. DNS — IP-адреса. MTU по умолчанию 1420, поддерживаемый диапазон 1280–9000.

## Обычная сессия

```bash
sudo python3 -m approute up /absolute/path/provider.conf
sudo python3 -m approute status
sudo python3 -m approute run -- curl https://api.ipify.org
sudo python3 -m approute run -- firefox --no-remote
sudo python3 -m approute down
```

Перед `down` закрыть запущенные через VPN приложения. Из root-сессии явно указать обычного пользователя:

```bash
python3 -m approute run --user alice -- curl https://api.ipify.org
```

Имя alice заменить своим. GUI зависит от доступа к сессии Wayland/X11. Для браузера с существующим процессом использовать отдельный экземпляр и при необходимости отдельный профиль.

## Проверка состояния

```bash
sudo ip -n approute-vpn address show
sudo ip -n approute-vpn route show
sudo ip -n approute-vpn -6 route show
sudo ip netns pids approute-vpn
sudo python3 -m approute status
```

Команды с namespace применимы после `up`. `VPN подключён` подтверждает завершение настройки; доступность сервера проверяется трафиком и свежим handshake.

## Частые ошибки

- Нет `wg`, `ip` или `runuser`: установить системные зависимости. Сейчас CLI проверяет все три команды для каждой операции.
- Нет root: запускать через sudo.
- Неподдерживаемый параметр: использовать отдельный совместимый конфиг без hooks, Table и SaveConfig; не запускать содержимое конфига вручную.
- Нет доступа к сайтам: проверить Endpoint, handshake, AllowedIPs, DNS и серверную маршрутизацию. Для полного IPv4-туннеля нужен `0.0.0.0/0`, для IPv6 — `::/0` и IPv6 Address.
- `down` выводит PID: закрыть соответствующие приложения и повторить команду.
- Найдены оставшиеся ресурсы: изучить status и список PID, затем выполнить `down`. Не удалять вслепую ресурсы, созданные другими инструментами.

При недоступности сервера внутри namespace нет прямого маршрута через физическую сеть. Проверять это по [сценарию тестирования](tests.md). Не запускать несколько операций управления одновременно.
