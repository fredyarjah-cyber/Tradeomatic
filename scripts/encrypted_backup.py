"""Opt-in encrypted PostgreSQL backup. No plaintext dump is written to disk."""
import os,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit,unquote
from cryptography.fernet import Fernet

def encode_backup(data,key):return Fernet(key.encode()).encrypt(data)
def backup():
    if os.getenv('BACKUP_ENABLED')!='true':raise ValueError('Backup job is not enabled')
    url=urlsplit(os.environ['DATABASE_URL'].replace('postgresql+psycopg://','postgresql://'))
    if url.scheme not in ('postgresql','postgres'):raise ValueError('PostgreSQL backup source required')
    env={**os.environ,'PGHOST':url.hostname,'PGPORT':str(url.port or 5432),'PGDATABASE':url.path.lstrip('/'),'PGUSER':unquote(url.username or ''),'PGPASSWORD':unquote(url.password or '')}
    process=subprocess.Popen(['pg_dump','-Fc'],env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    data=process.stdout.read(100*1024*1024+1)
    if len(data)>100*1024*1024:process.kill();process.wait();raise ValueError('Backup exceeds configured 100 MB in-memory limit')
    if process.wait()!=0:raise ValueError('Backup command failed; details redacted')
    result=encode_backup(data,os.environ['BACKUP_ENCRYPTION_KEY']);root=Path(os.getenv('BACKUP_DIRECTORY','/backups'));root.mkdir(parents=True,exist_ok=True)
    path=root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.dump.fernet');temp=path.with_suffix('.tmp');temp.write_bytes(result);temp.chmod(0o600);temp.replace(path)
    for old in sorted(root.glob('*.dump.fernet'),reverse=True)[7:]:old.unlink()
    return path
if __name__=='__main__':
    if os.getenv('BACKUP_LOOP')=='true':
        last=None
        while True:
            day=datetime.now(timezone.utc).date()
            if day!=last:
                try:backup();last=day
                except Exception:pass
            time.sleep(60)
    else:print('Encrypted backup saved:',backup().name)
