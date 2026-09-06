"""Bundle the V3 reader without a runtime dependency on neighbouring files."""
from layout import PRODUCT, DATA, TOOLS
import base64
import json
from pathlib import Path


def bundle(project: Path, out: Path):
    files = {}
    evidence=json.loads((DATA/'implementation-v3.json').read_text(encoding='utf-8'))
    public_images={s['file'] for s in evidence['screenshots'] if not s.get('publicExcluded')}
    tutorial=DATA/'tutorial-v3.json'
    if tutorial.exists():public_images.update(s['file'] for s in json.loads(tutorial.read_text(encoding='utf-8'))['screenshots'])
    for path in sorted((out/'assets'/'evidence').glob('*.png')):
        if path.name not in public_images:
            continue
        files[path.relative_to(out).as_posix()] = {
            'mime': 'image/png', 'base64': base64.b64encode(path.read_bytes()).decode('ascii')}
    for name, mime in [('product-expanded.json','application/json'),
                       ('AI_产品定义与需求推导.md','text/markdown'),
                       ('AI_新产品需求导图.opml','text/xml')]:
        files[name] = {'mime':mime, 'base64':base64.b64encode((out/name).read_bytes()).decode('ascii')}
    documents = {}
    for path in sorted((PRODUCT/'reading').glob('*.md')):
        documents[path.name] = {
            'title':path.stem.removeprefix('AI_'),
            'text':path.read_text(encoding='utf-8'),
            'notice': '产品参考 · 对应 v0.4.26 功能说明'}
    documents['第三方声明.md'] = {'title':'第三方资产声明','notice':'离线渲染资产的来源与许可。',
        'text':(TOOLS/'vendor'/'NOTICE.txt').read_text(encoding='utf-8')}
    for folder, name in [
            ('development', '开发约定.md'), ('development', '架构总览.md'),
            ('usage', 'API契约.md'), ('usage', '界面导览.md'), ('usage', '报文解读.md')]:
        path = project / 'docs' / folder / name
        text = path.read_bytes().decode('utf-8')
        if len(text) < 2000:
            raise SystemExit(f'{path}: 正文不足，拒绝内嵌空壳参考')
        documents[name] = {'title': path.stem, 'text': text,
            'notice': f'当前参考正文来自 docs/{folder}/{name}；历史实现和截图仍按其原始基线标注。'}
    payload=json.dumps({'files':files,'documents':documents},ensure_ascii=False).replace('<','\\u003c')
    html=(out/'index.html').read_text(encoding='utf-8')
    for name in ('marked.min.js','purify.min.js'):
        code=(TOOLS/'vendor'/name).read_text(encoding='utf-8').replace('</script','<\\/script')
        html=html.replace(f'<script src="assets/vendor/{name}"></script>',f'<script>{code}</script>')
    runtime=(TOOLS/'templates'/'book.js').read_text(encoding='utf-8')
    html=html.replace('<script id="data"',f'<script id="bookData" type="application/json">{payload}</script><script>{runtime}</script><script id="data"')
    (out/'index.html').write_text(html,encoding='utf-8')
    return {'bytes':len(html.encode('utf-8')),'images':sum(x['mime']=='image/png' for x in files.values()),'documents':len(documents)}
