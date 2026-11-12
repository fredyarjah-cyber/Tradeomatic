"""Package reproducible source and built dashboard; exclude databases and secrets."""
import zipfile
from pathlib import Path
with zipfile.ZipFile('dist/tradeomatic-ai-source.zip','w',zipfile.ZIP_DEFLATED) as z:
    for base in ['backend','src','tests','dist','scripts','reports','docs','deploy']:
        for p in Path(base).rglob('*'):
            if p.is_file() and '__pycache__' not in str(p) and p.suffix!='.zip':z.write(p,'tradeomatic-ai/'+str(p))
    for n in ['README.md','Dockerfile','compose.yaml','requirements.txt','package.json','package-lock.json','.env.example','.gitignore']:
        z.write(n,'tradeomatic-ai/'+n)
print('Source archive prepared: dist/tradeomatic-ai-source.zip')
