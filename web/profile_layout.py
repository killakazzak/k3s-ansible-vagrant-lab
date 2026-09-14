"""Profiles own configuration/state and link to the checkout's common code."""
import os
import shutil
import time
from pathlib import Path

TOP_FILES = ('Vagrantfile', 'cluster.sh', 'deploy.sh', 'kubectl.sh', 'ansible.cfg')

def links(source):
    source=Path(source)
    result={name:source/name for name in (*TOP_FILES,'scripts','web','vendor')}
    for item in (source/'ansible').iterdir():
        if item.name not in ('inventory.yml','group_vars'):
            result['ansible/'+item.name]=item
    return result

def initialize(source, target):
    source,target=Path(source),Path(target)
    (target/'ansible').mkdir(exist_ok=True)
    shutil.copytree(source/'ansible/group_vars',target/'ansible/group_vars')
    shutil.copy2(source/'ansible/inventory.yml',target/'ansible/inventory.yml')
    for name,origin in links(source).items():
        dest=target/name
        dest.symlink_to(os.path.relpath(origin,dest.parent),target_is_directory=origin.is_dir())

def migrate(source, target):
    source,target=Path(source).resolve(),Path(target).resolve()
    if target.parent != source/'.clusters' or not (target/'ansible/inventory.yml').is_file():
        raise ValueError('Not a cluster profile of this checkout')
    backup=source/'.cache/profile-code-backups'/str(time.time_ns())/target.name
    changed=[]
    for name,origin in links(source).items():
        dest=target/name
        if dest.is_symlink() and os.readlink(dest)==os.path.relpath(origin,dest.parent):continue
        if dest.exists() or dest.is_symlink():
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True)
            dest.rename(saved)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.symlink_to(os.path.relpath(origin,dest.parent),target_is_directory=origin.is_dir())
        changed.append(name)
    return changed
