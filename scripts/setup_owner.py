"""Run locally on the backend host. Never paste these secrets into chat."""
import getpass, os
from backend import db
from backend.security import encrypt,HASHER
import pyotp

def main():
    if not os.getenv('ENCRYPTION_KEY'):raise SystemExit('Set a persistent ENCRYPTION_KEY in the server secret manager first.')
    db.init()
    if db.get('auth','owner'):raise SystemExit('Owner already exists. This setup will not overwrite credentials.')
    username=input('Owner username: ').strip();password=getpass.getpass('New password (at least 14 characters): ')
    if len(password)<14 or not username:raise SystemExit('Username and a password of at least 14 characters required.')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords differ.')
    secret=pyotp.random_base32();totp=pyotp.TOTP(secret)
    print('Add this setup key to your authenticator app on your own device:',secret)
    code=input('Enter its current 6-digit code to finish setup: ').strip()
    if not totp.verify(code,valid_window=0):raise SystemExit('Authenticator verification failed; nothing was saved.')
    db.put('auth','owner',{'username':username,'password_hash':HASHER.hash(password),'totp_secret':encrypt(secret),'last_totp_counter':-1})
    print('Owner configured. Keep encrypted backups and the encryption key separate.')
if __name__=='__main__':main()
