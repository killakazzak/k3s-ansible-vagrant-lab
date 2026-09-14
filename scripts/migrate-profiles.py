#!/usr/bin/env python3
"""Link existing profiles to shared code without touching VM/configuration data."""
import sys, json, urllib.request, urllib.parse
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'web'))
from profile_layout import migrate

def main():
    lock=root/'.cache/web.lock'
    if lock.exists():
        url=json.loads(lock.read_text())['url'];parts=urllib.parse.urlsplit(url)
        token=urllib.parse.parse_qs(parts.fragment)['token'][0]
        try:
            job=json.load(urllib.request.urlopen(urllib.request.Request('http://'+parts.netloc+'/api/job',headers={'X-Lab-Token':token}),timeout=10))
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason,ConnectionRefusedError):raise
            job=None
        if job and job.get('state')=='running':raise SystemExit('Дождитесь завершения операции с кластером перед миграцией.')
    for target in sorted((root/'.clusters').glob('*')):
        if target.is_symlink() or not (target/'ansible/inventory.yml').is_file():continue
        changed=migrate(root,target)
        print(target.name+': '+str(len(changed))+' общих ссылок обновлено')
if __name__=='__main__':main()
