#!/usr/bin/env python3
"""Fetch Bento's ISO visibly, resume partial downloads, verify before Packer."""
import hashlib,json,re,subprocess,sys,time,fcntl,shutil,os,tempfile
from pathlib import Path

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def migrate_legacy(cache, expected, name, project=None):
    project=project or Path(__file__).resolve().parents[1]
    bases=[project/'.cache/box25/iso', *project.glob('.clusters/*/.cache/box25/iso')]
    destination=cache/expected[:16]/name
    destination.parent.mkdir(parents=True,exist_ok=True)
    for base in bases:
        source=base/expected[:16]/name
        if source.resolve()==destination.resolve():continue
        if source.is_file() and not source.is_symlink() and not destination.exists() and digest(source)==expected:
            fd,temporary=tempfile.mkstemp(prefix='.migrate-',dir=destination.parent);os.close(fd)
            try:
                shutil.copyfile(source,temporary)
                if digest(Path(temporary))!=expected:raise ValueError('ISO migration checksum mismatch')
                os.replace(temporary,destination)
                source.unlink()
                print('[ISO] Moved verified ISO to shared cache: '+str(destination),flush=True)
            finally:
                Path(temporary).unlink(missing_ok=True)
        old_partial=source.with_name(name+'.part');new_partial=destination.with_name(name+'.part')
        if not destination.exists() and not new_partial.exists() and old_partial.is_file() and not old_partial.is_symlink():
            shutil.move(str(old_partial),str(new_partial))
            print('[ISO] Moved partial download to shared cache: '+str(new_partial),flush=True)

def main():
    cache=Path(sys.argv[2]);cache.mkdir(parents=True,exist_ok=True)
    with (cache/'.download.lock').open('a') as lock:
        print('[ISO] Shared cache: '+str(cache.resolve()),flush=True)
        fcntl.flock(lock,fcntl.LOCK_EX)
        prepare()

def prepare():
    variables,cache,output=map(Path,sys.argv[1:])
    text=variables.read_text()
    def value(key):
        match=re.search(r'^'+key+r'\s*=\s*("[^"\n]*")',text,re.M)
        if not match:raise ValueError('Missing ISO setting: '+key)
        return json.loads(match[1])
    url=value('iso_url');checksum=value('iso_checksum')
    if not url.startswith('https://'):raise ValueError('ISO source must use HTTPS')
    from urllib.parse import urlsplit,unquote
    name=Path(unquote(urlsplit(url).path)).name
    cache.mkdir(parents=True,exist_ok=True)
    if checksum.startswith('file:https://'):
        sums=cache/'SHA256SUMS'
        subprocess.run(['bash',str(Path(__file__).with_name('download.sh')),'Ubuntu ISO SHA256',checksum[5:],str(sums)],check=True)
        matches=[line.split()[0] for line in sums.read_text().splitlines() if len(line.split())==2 and line.split()[1].lstrip('*')==name]
        if len(matches)!=1:raise ValueError('ISO not found in SHA256SUMS: '+name)
        expected=matches[0]
    else:expected=checksum.removeprefix('sha256:')
    if not re.fullmatch('[a-fA-F0-9]{64}',expected):raise ValueError('Invalid ISO SHA256')
    expected=expected.lower();folder=cache/expected[:16];folder.mkdir(exist_ok=True)
    migrate_legacy(cache,expected,name)
    iso=folder/name;partial=folder/(name+'.part')
    if iso.exists() and digest(iso)==expected:
        print('[ISO] Verified cached image: '+str(iso),flush=True)
    else:
        print('[ISO] Download: '+url,flush=True)
        for attempt in range(1,5):
            print(f'[ISO] Attempt {attempt}/4; connect timeout 10s; stall timeout 30s',flush=True)
            initial=partial.stat().st_size if partial.exists() else 0
            started=time.monotonic();last=started
            args=['curl','--fail','--location','--silent','--show-error','--connect-timeout','10','--speed-time','30','--speed-limit','1024','--max-time','3600','-C','-','-o',str(partial),url]
            process=subprocess.Popen(args)
            try:
                while process.poll() is None:
                    now=time.monotonic()
                    if now-last>=5:
                        size=partial.stat().st_size if partial.exists() else 0
                        print(f'[ISO] {size/1024**2:.1f} MiB downloaded | {(size-initial)/1024**2/max(now-started,1):.2f} MiB/s | {int(now-started)}s',flush=True);last=now
                    time.sleep(.2)
            finally:
                if process.poll() is None:process.terminate();process.wait()
            if process.returncode==0:break
            print(f'[ISO] curl failed: {process.returncode}; partial download retained',flush=True)
            if process.returncode in (33,36):
                partial.unlink(missing_ok=True)
                print('[ISO] Server does not support resume; retrying from zero',flush=True)
            if attempt==4:raise RuntimeError('ISO download failed. Retry deployment to resume: '+str(partial))
            time.sleep(2)
        print('[ISO] Verifying SHA256...',flush=True)
        if digest(partial)!=expected:
            partial.unlink()
            raise ValueError('ISO checksum mismatch; corrupt download removed. Retry deployment.')
        partial.replace(iso)
    output.write_text(json.dumps({'iso_url':str(iso.resolve()),'iso_checksum':'sha256:'+expected}))
    print('[ISO] Ready; Packer will use the local file.',flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:print('[ISO] '+str(error),file=sys.stderr,flush=True);sys.exit(1)
