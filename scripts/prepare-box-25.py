"""Exclude UTM-only plugin blocks from the pinned Bento VirtualBox build."""
import sys
from pathlib import Path
root = Path(sys.argv[1]) / 'packer_templates'
for filename, start in [('pkr-plugins.pkr.hcl', '    utm = {'), ('pkr-sources.pkr.hcl', 'source "utm-iso" "vm" {'), ('pkr-builder.pkr.hcl', '  post-processor "utm-vagrant" {')]:
    path = root / filename
    text = path.read_text()
    if start not in text:
        continue
    begin = text.index(start)
    end = text.index('{', begin) + 1
    depth = 1
    while depth:
        if text[end] == '{': depth += 1
        if text[end] == '}': depth -= 1
        end += 1
    path.write_text(text[:begin] + text[end:])
# Recent VirtualBox builders name the default IDE controller "IDE".
path = root / 'pkr-sources.pkr.hcl'
text = path.read_text()
path.write_text(text.replace('"IDE Controller", "--remove"', '"IDE", "--remove"'))
# Resolve guest NAT DNS through macOS (including its VPN resolver).
text = path.read_text()
needle = '["modifyvm", "{{.Name}}", "--nat-localhostreachable1", "on"],'
replacement = needle + '\n        ["modifyvm", "{{.Name}}", "--natdnshostresolver1", "on"],'
if '--natdnshostresolver1' not in text:
    path.write_text(text.replace(needle, replacement))
# Use the same persistent resolver as the lab before any package downloads.
script = root / 'scripts/_common/box25_dns.sh'
script.write_text('''#!/bin/sh
set -eu
mkdir -p /etc/systemd/resolved.conf.d
cat > /etc/systemd/resolved.conf.d/60-k3s-lab.conf <<'DNS'
[Resolve]
DNS=1.1.1.1 1.0.0.1
DNSOverTLS=yes
Domains=~.
DNS
systemctl restart systemd-resolved
''')
path = root / 'pkr-builder.pkr.hcl'
text = path.read_text()
needle = 'scripts           = ["${path.root}/scripts/_common/update_packages.sh", ]'
text = text.replace(needle, 'scripts           = ["${path.root}/scripts/_common/box25_dns.sh", "${path.root}/scripts/_common/update_packages.sh", ]')
path.write_text(text)
