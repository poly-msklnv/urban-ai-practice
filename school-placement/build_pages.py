"""Build a standalone GitHub Pages app without a Python backend."""
import gzip
import json
import shutil
from pathlib import Path

import numpy as np

from model import MATRIX, RESULT_COLUMNS, ROOT, load_model, read_blocks

HERE=Path(__file__).resolve().parent
OUT=ROOT/'dist/school-placement'

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    blocks=read_blocks(); model=load_model(blocks)
    features=json.loads(blocks[['geometry']].to_crs(4326).to_json())
    for i,feature in enumerate(features['features']): feature['properties']={'block_id':i}
    data={'ready':True,'error':None,'geometry':features,'geometry_crs':'EPSG:4326',
          'baseline':model.payload(model.baseline),
          'indicators':json.loads(blocks[RESULT_COLUMNS].to_json(orient='records'))}
    with gzip.GzipFile(str(OUT/'web-data.json.gz'),'wb',mtime=0) as f:
        f.write(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode())
    with gzip.GzipFile(str(OUT/'matrix.bin.gz'),'wb',mtime=0) as f:
        f.write(np.asarray(model.matrix,dtype='<f8').tobytes())
    for name in ['main.js','style.css','browser-model.mjs','browser-backend.js','solver-worker.mjs']:
        shutil.copy2(HERE/name,OUT/name)
    for name in ['vendor','demo','screenshots']:
        shutil.copytree(HERE/name,OUT/name,dirs_exist_ok=True)
    page=(HERE/'index.html').read_text().replace('<script src="main.js" defer></script>',
        '<script src="browser-backend.js" defer></script><script src="main.js" defer></script>')
    page=page.replace('Метод: competitive_provision, BlocksNet 1.0.0a9;', 'Метод: целочисленная модель competitive_provision из BlocksNet 1.0.0a9, решатель HiGHS WebAssembly;')
    page=page.replace('Сравните варианты по сокращению дефицита мест в пределах 15 минут пешком.',
        'Сравните варианты по сокращению дефицита мест в пределах 15 минут пешком. Расчёты выполняются в вашем браузере.')
    page=page.replace('</header>', '<p><a href="demo/school-placement-demo.mp4">Видео демонстрации, 1:33</a></p></header>')
    (OUT/'index.html').write_text(page)
    (OUT/'.nojekyll').touch()
    print(OUT)
