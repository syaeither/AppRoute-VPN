"""Linux network namespace launcher. No shell interpolation or config hooks."""
import argparse
import ipaddress
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import uuid

NS = 'approute-vpn'
IFACE = 'arwg0'
DNS_DIR = Path('/etc/netns') / NS


def command(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def parse_config(text):
    section = None
    addresses, dns, output = [], [], []
    mtu = 1420
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('['):
            if line not in ('[Interface]', '[Peer]'):
                raise ValueError('Неизвестная секция конфигурации')
            section = line
            output.append(line)
            continue
        if '=' not in line or section is None:
            raise ValueError('Некорректная конфигурация WireGuard')
        key, value = (part.strip() for part in line.split('=', 1))
        if section == '[Interface]' and key in ('Address', 'DNS', 'MTU'):
            if key == 'Address':
                addresses.extend(str(ipaddress.ip_interface(x.strip())) for x in value.split(','))
            elif key == 'DNS':
                dns.extend(str(ipaddress.ip_address(x.strip())) for x in value.split(','))
            else:
                mtu = int(value)
                if not 1280 <= mtu <= 9000:
                    raise ValueError('MTU должен быть от 1280 до 9000')
            continue
        allowed = {'PrivateKey', 'ListenPort'} if section == '[Interface]' else {
            'PublicKey', 'PresharedKey', 'AllowedIPs', 'Endpoint', 'PersistentKeepalive'}
        if key not in allowed:
            raise ValueError(f'Неподдерживаемый параметр: {key}. Hooks не выполняются.')
        output.append(f'{key} = {value}')
    if not addresses or not dns:
        raise ValueError('Укажите Address и DNS (IP-адреса) в [Interface]')
    return '\n'.join(output) + '\n', addresses, dns, mtu


def exists():
    return Path('/run/netns', NS).exists()


def up(config):
    conf, addresses, dns, mtu = parse_config(Path(config).read_text())
    if exists() or DNS_DIR.exists():
        raise ValueError('AppRoute уже подключён или остались ресурсы; проверьте status/down')
    temporary_interface = 'ar' + uuid.uuid4().hex[:10]
    created_ns = created_link = moved = created_dns = False
    try:
        command('ip', 'netns', 'add', NS)
        created_ns = True
        command('ip', 'link', 'add', temporary_interface, 'type', 'wireguard')
        created_link = True
        # Configure in host namespace: endpoint hostnames resolve using host DNS.
        with tempfile.NamedTemporaryFile(mode='w', prefix='approute-', suffix='.conf') as f:
            f.write(conf)
            f.flush()
            command('wg', 'setconf', temporary_interface, f.name)
        command('ip', 'link', 'set', temporary_interface, 'netns', NS)
        moved = True
        command('ip', '-n', NS, 'link', 'set', temporary_interface, 'name', IFACE)
        command('ip', '-n', NS, 'link', 'set', 'lo', 'up')
        for address in addresses:
            command('ip', '-n', NS, 'address', 'add', address, 'dev', IFACE)
        command('ip', '-n', NS, 'link', 'set', IFACE, 'mtu', str(mtu), 'up')
        for family in sorted({ipaddress.ip_interface(a).version for a in addresses}):
            command('ip', '-n', NS, f'-{family}', 'route', 'add', 'default', 'dev', IFACE)
        DNS_DIR.mkdir(parents=True)
        created_dns = True
        (DNS_DIR / 'resolv.conf').write_text(''.join(f'nameserver {d}\n' for d in dns))
    except BaseException:
        if created_link and not moved:
            command('ip', 'link', 'del', temporary_interface, check=False)
        if created_ns:
            command('ip', 'netns', 'del', NS, check=False)
        if created_dns:
            (DNS_DIR / 'resolv.conf').unlink(missing_ok=True)
            DNS_DIR.rmdir()
        raise
    print('VPN подключён. Запускайте приложения командой run.')


def down():
    if exists():
        pids = command('ip', 'netns', 'pids', NS).stdout.strip()
        if pids:
            raise ValueError('Сначала закройте приложения в VPN. PID: ' + ', '.join(pids.split()))
        command('ip', 'netns', 'del', NS)
    if DNS_DIR.exists():
        (DNS_DIR / 'resolv.conf').unlink(missing_ok=True)
        DNS_DIR.rmdir()
    print('VPN отключён.')


def main():
    parser = argparse.ArgumentParser(description='AppRoute VPN — VPN для выбранных приложений (Linux)')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('up').add_argument('config', help='WireGuard .conf с Address и DNS')
    sub.add_parser('down')
    sub.add_parser('status')
    launch = sub.add_parser('run')
    launch.add_argument('--user', default=os.environ.get('SUDO_USER'))
    launch.add_argument('program', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if sys.platform != 'linux':
            raise ValueError('Этот MVP поддерживает только Linux')
        if os.geteuid() != 0:
            raise ValueError('Запустите через sudo: необходимы права управления сетью')
        for tool in ('ip', 'wg', 'runuser'):
            if not shutil.which(tool):
                raise ValueError(f'Не найдена команда {tool}; установите iproute2, wireguard-tools, util-linux')
        if args.action == 'up':
            up(args.config)
        elif args.action == 'down':
            down()
        elif args.action == 'status':
            if not exists():
                print('VPN отключён.')
            else:
                print(command('ip', 'netns', 'exec', NS, 'wg', 'show', IFACE).stdout, end='')
        else:
            if not exists():
                raise ValueError('Сначала выполните up')
            program = args.program
            if program and program[0] == '--':
                program = program[1:]
            if not program or not args.user:
                raise ValueError('Укажите --user USER и команду после --')
            account = pwd.getpwnam(args.user)
            if account.pw_uid == 0:
                raise ValueError('Приложения должны запускаться от обычного пользователя')
            os.execvp('ip', ['ip', 'netns', 'exec', NS, 'runuser', '-u', args.user, '--', *program])
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print('Ошибка: ' + detail, file=sys.stderr)
        sys.exit(1)
