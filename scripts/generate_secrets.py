"""Run on your own computer. Save these values in your hosting secret manager."""
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def generate():
    key=ec.generate_private_key(ec.SECP256R1())
    enc=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    return {'ENCRYPTION_KEY':Fernet.generate_key().decode(),'VAPID_PRIVATE_KEY':enc(key.private_numbers().private_value.to_bytes(32,'big')),'VAPID_PUBLIC_KEY':enc(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))}
if __name__=='__main__':
    print('PRIVATE SETUP VALUES: do not paste into chat or commit to source control.')
    for k,v in generate().items():print(k+'='+v)
