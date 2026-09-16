"""Local IPv4 interface discovery and HTTP authority validation."""
import ipaddress
import re
import shutil
import socket
import subprocess
from urllib.parse import urlsplit


def local_ipv4():
    addresses = {'127.0.0.1'}
    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    command = [shutil.which('ip'), '-o', '-4', 'addr', 'show'] if shutil.which('ip') else [shutil.which('ifconfig') or '/sbin/ifconfig']
    try:
        output = subprocess.run(command, capture_output=True, text=True, timeout=3, check=True).stdout
        addresses.update(re.findall(r'\binet\s+(\d+\.\d+\.\d+\.\d+)', output))
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(a for a in addresses if not ipaddress.ip_address(a).is_unspecified and not ipaddress.ip_address(a).is_reserved)


def valid_authority(authority, port):
    if not authority or any(c in authority for c in '/?#@ \\'):
        return False
    try:
        parsed = urlsplit('http://' + authority)
        if (parsed.port or 80) != port:
            return False
        host = parsed.hostname
        if host in {'localhost', socket.gethostname().lower(), socket.getfqdn().lower()}:
            return True
        address = ipaddress.IPv4Address(host)
        if address.is_unspecified or address.is_multicast:
            return False
        # Binding verifies that this address belongs to this computer, including
        # interfaces added after server startup. No connection is accepted.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((str(address), 0))
        return True
    except (ValueError, TypeError, OSError):
        return False
