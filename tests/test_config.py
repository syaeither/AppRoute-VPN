import unittest
from unittest.mock import patch
from approute.cli import parse_config, up

BASE = '[Interface]\nPrivateKey = secret\nAddress = 10.0.0.2/32, fd00::2/128\nDNS = 1.1.1.1\n[Peer]\nPublicKey = peer\nAllowedIPs = 0.0.0.0/0, ::/0\n'


class ConfigTests(unittest.TestCase):
    def test_extracts_network_settings(self):
        config, addresses, dns, mtu = parse_config(BASE)
        self.assertEqual(addresses, ['10.0.0.2/32', 'fd00::2/128'])
        self.assertEqual(dns, ['1.1.1.1'])
        self.assertEqual(mtu, 1420)
        self.assertNotIn('Address', config)
        self.assertIn('PrivateKey = secret', config)

    def test_rejects_hooks(self):
        with self.assertRaises(ValueError):
            parse_config(BASE.replace('PrivateKey = secret', 'PostUp = echo unsafe'))

    def test_requires_explicit_dns(self):
        with self.assertRaises(ValueError):
            parse_config(BASE.replace('DNS = 1.1.1.1\n', ''))

    def test_invalid_address(self):
        with self.assertRaises(ValueError):
            parse_config(BASE.replace('10.0.0.2/32', 'bad'))

    def test_rolls_back_owned_resources_on_failure(self):
        with patch('approute.cli.Path.read_text', return_value=BASE), \
             patch('approute.cli.exists', return_value=False), \
             patch('approute.cli.Path.exists', return_value=False), \
             patch('approute.cli.command') as cmd:
            calls = []
            def execute(*args, **kwargs):
                calls.append(args)
                if args[:2] == ('wg', 'setconf'):
                    raise OSError('failure')
            cmd.side_effect = execute
            with self.assertRaises(OSError):
                up('example.conf')
            self.assertEqual(calls[-1], ('ip', 'netns', 'del', 'approute-vpn'))
            self.assertEqual(calls[-2][:3], ('ip', 'link', 'del'))


if __name__ == '__main__':
    unittest.main()
