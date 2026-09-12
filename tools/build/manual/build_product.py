"""Generate the product-discovery map and portable outlines."""
import json
import sys
import hashlib
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

from layout import ROOT, PRODUCT, DATA, TOOLS, OUT
VERSION='v3'
SRC=DATA/f'product-{VERSION}.json'
OUT.mkdir(parents=True,exist_ok=True)
data=json.loads(SRC.read_text(encoding='utf-8'))
data['version']=VERSION
modern=VERSION=='v3'
data['presentation']={
    'heading':'CCWA · 产品说明书' if modern else '新产品，从问题开始',
    'subtitle':data['subtitle'],
    'label':'功能 / 使用 / 要求 / 后续设计' if modern else '建议定位 · 可以修改',
    'note':'已有软件与本版新增设计并列维护。实现状态、代码证据与截图分别标注，避免把设计当成已完成。' if modern else '产品定位与首版范围为待验证提案。',
    'reading':'先读 README 了解项目，再用本书深入阅读：从第 0 节认识产品，沿工作流查用法、设计与限制；协作方式见顶部“三类文档与协作”。后续设计不代表已经实现。' if modern else '先讨论用户、问题和定位，再选择功能。',
    'groupSuffix':'按所在工作流归属；待定方向不等于已否决或已承诺交付。' if modern else '不默认全部进入首版。'
}
catalog=json.loads((DATA/'capabilities.json').read_text(encoding='utf-8'))
requirements={i['id']:i for g in catalog['groups'] for i in g['items']}
for rid, correction in data.get('requirementOverrides', {}).items():
    assert rid in requirements and correction.get('reason'), rid
    assert set(correction) <= {'title','need','acceptance','reason'}, rid
    requirements[rid] = {**requirements[rid], **{k:v for k,v in correction.items() if k != 'reason'}}
    requirements[rid]['acceptance'] += '\n\n本版裁定：' + correction['reason']
GAPS=DATA/f'gaps-{VERSION}.json'
gaps=json.loads(GAPS.read_text(encoding='utf-8')) if GAPS.exists() else {'items':[]}
for gap in gaps['items']:
    assert gap['id'] not in requirements, f"gap id collides with catalog: {gap['id']}"
    assert gap.get('derivedFrom') and gap.get('need') and gap.get('acceptance'), gap['id']
    requirements[gap['id']]=gap
review=data.get('reviewNotes',{})
REVIEW_LABEL={'redundant':'⚑ 冗余候选','misplaced':'⚑ 归属存疑','tension':'⚑ 与承诺张力'}
types={
    'A-01':'产品目标','A-02':'使用者参考','A-03':'验证工作','A-04':'观测边界','A-05':'兼容范围',
    'B-02':'安全约束','B-04':'安全约束','C-01':'数据正确性','C-02':'功能与保真约束',
    'C-03':'数据正确性','C-06':'数据正确性','C-07':'计量约束','C-08':'安全约束','C-09':'证据策略',
    'D-02':'实现候选','D-07':'验证工作','D-08':'实现候选','E-06':'数据模型约束',
    'H-05':'分析约束','H-06':'验证约束','J-06':'解释约束',
    'K-04':'输出约束','L-03':'功能要求','L-07':'文档与发布要求',
    'M-01':'安全约束','M-02':'安全约束','M-03':'功能与隐私约束','M-04':'安全约束',
    'M-05':'验证工作','M-06':'验证工作','M-07':'验证工作','M-08':'规模验证',
    'N-06':'实现候选','N-11':'所有权约束'
}
manual_file=DATA/f'manual-{VERSION}.json'
data['manualCount']=0
if manual_file.exists():
    manual=json.loads(manual_file.read_text(encoding='utf-8'))
    def manual_targets(ns):
        for n in ns:
            yield n
            yield from manual_targets(n['children'])
    parents={n['id']:n for n in manual_targets(data['tree'])}
    for section in manual['sections']:
        assert section['target'] in parents and section['body']
        if isinstance(section.get('basis'), list):
            section['basis']='来源：原软件 '+ '；'.join(section['basis'])
        parents[section['target']]['children'].insert(0,{k:v for k,v in section.items() if k!='target'} | {'children':[],'manual':True})
    data['manualCount']=len(manual['sections'])
mapped=[]
data['readingCount']=0
if modern:
    for name in ('reading-v3.json','research-reading-v3.json','principles-v3.json','reference-v3.json'):
        source=DATA/name
        assert source.exists(), f'Missing integrated reading source: {name}'
        supplement=json.loads(source.read_text(encoding='utf-8'))
        def reading_targets(ns):
            for n in ns:
                yield n
                yield from reading_targets(n['children'])
        parents={n['id']:n for n in reading_targets(data['tree'])}
        for section in supplement['sections']:
            assert section['target'] in parents and section['body'], section['id']
            node={k:v for k,v in section.items() if k!='target'}
            node.setdefault('children',[])
            if isinstance(node.get('basis'),list):node['basis']='；'.join(node['basis'])
            node['reading']=True
            parents[section['target']]['children'].append(node)
            data['readingCount']+=1
def enrich(nodes):
    for node in nodes:
        enrich(node['children'])
        for group in node.get('featureGroups',[]):
            children=[]
            for rid in group['items']:
                item=requirements[rid];mapped.append(rid)
                kind=types.get(rid,'可选呈现' if group['role']=='可选呈现' else '功能')
                if 'derivedFrom' in item:
                    origin=f'推导来源：{item["derivedFrom"]}'
                    state=f'\n参考状态：{item["status"]}（由新产品逻辑推出，旧能力库无对应条目，不表示已有实现）。'
                else:
                    origin='来源：'+'；'.join(f'{catalog["sources"][s][0]}（{catalog["sources"][s][1]}）' for s in item['sources'])
                    state=f'\n参考状态：{item["status"]}（原能力库状态，不等于新产品已实现）。'
                marks=[f'{REVIEW_LABEL[key]}：{table[rid]}' for key,table in review.items() if rid in table]
                body=(f'{item["need"]}\n\n条目性质：{kind}。规划归属：{group["role"]}。{state}'
                      f'\n\n验收条件：{item["acceptance"]}\n\n{origin}'
                      +(('\n\n'+'\n'.join(marks)) if marks else ''))
                basis=''
                if modern:
                    acceptance, _, ruling = item['acceptance'].partition('\n\n本版裁定：')
                    basis=(origin if 'derivedFrom' in item else '具体操作与适用范围见所在章节的使用方法和当前功能说明。')+(('\n\n'+ '\n'.join(marks)) if marks else '')
                    if 'derivedFrom' in item:
                        basis+='\n\n旧能力库无对应条目，属于新增设计，尚未实现。'
                    availability={'现有':'当前软件已有相关能力，具体用法与限制见本节说明。','部分':'当前仅提供部分能力；完整行为属于功能要求，差异见本节当前功能说明。','构想':'后续设计，尚未作为完整功能提供。','新增建议':'后续设计，尚未提供。'}.get(item['status'],'后续设计，尚未提供。')
                    body=f'**功能要求**\n\n{item["need"]}\n\n{acceptance}\n\n**提供情况**：{availability}'
                children.append({'id':'cap-'+rid,'title':item['title'],'body':body,'basis':basis,'children':[],
                                 'refs':[node['id']],'catalogId':rid,'itemType':kind})
            node['children'].append({'id':group['id'],'title':group['title'],
                'body':group['why'] if modern else f'{group["why"]}\n\n{group["role"]} · {len(children)}项具体条目；{data["presentation"]["groupSuffix"]}',
                'children':children,'detailGroup':True})
enrich(data['tree'])
assert len(mapped)==len(set(mapped))==len(requirements), 'Catalog items must have exactly one primary home'
assert set(mapped)==set(requirements)
for key,table in review.items():
    assert key in REVIEW_LABEL, key
    for rid in table:
        assert rid in requirements, f'review note points at unknown item: {rid}'
data['reviewCounts']={k:len(v) for k,v in review.items()}
data['gapCount']=len(gaps['items'])
data['detailCount']=len(mapped)
evidence_file=DATA/f'implementation-{VERSION}.json'
data['evidenceCount']=0
if evidence_file.exists():
    evidence=json.loads(evidence_file.read_text(encoding='utf-8'))
    def find_nodes(ns):
        for n in ns:
            yield n
            yield from find_nodes(n['children'])
    targets={n['id']:n for n in find_nodes(data['tree'])}
    shots={s['id']:s for s in evidence['screenshots'] if not (modern and s.get('publicExcluded'))}
    sources={s['id']:s for s in evidence['sources']}
    asset_dir=OUT/'assets'/'evidence';asset_dir.mkdir(parents=True,exist_ok=True)
    for s in shots.values():
        image_path=(PRODUCT/s['asset']).resolve()
        assert image_path.is_relative_to((PRODUCT/'assets').resolve())
        assert hashlib.sha256(image_path.read_bytes()).hexdigest()==s['sha256']
        shutil.copyfile(image_path,asset_dir/s['file'])
    for p in evidence['panels']:
        assert p['target'] in targets
        assert all(r in requirements for r in p['requirements'])
        code=[]
        for sid in p['code']:
            s=sources[sid]
            assert hashlib.sha256(s['excerpt'].encode()).hexdigest()==s['excerptSha256']
            language='javascript' if s['file'].endswith('.html') else 'python'
            code.append({'id':p['id']+'-code-'+sid,'title':'代码证据：'+s['anchor'],
                'body':f"文件：`{s['file']}`，行 {s['startLine']}–{s['endLine']}。\n\n只读截取于 {evidence['checkedOn']}，基线 {evidence['baseline']}。这是局部实现证据，不是运行测试结果。\n\n```{language}\n{s['excerpt']}\n```\n\n片段 SHA-256：`{s['excerptSha256']}`",
                'children':[],'evidenceCode':True})
        images=[{'src':'assets/evidence/'+shots[sid]['file'],'title':shots[sid]['title'],
                 'note':shots[sid]['note'],'originalSource':shots[sid]['source'],'sha256':shots[sid]['sha256']} for sid in p['images'] if sid in shots]
        body=f"**功能介绍**\n\n{p['how']}\n\n**操作流程**\n\n{p['flow']}\n\n**使用限制与后续设计**\n\n{p['gap']}\n\n说明对应 {evidence['baseline']}，更新于 {evidence['checkedOn']}。"
        targets[p['target']]['children'].append({'id':p['id'],'title':p['title'],'body':body,'children':code,
            'images':images,'implementation':True,'refs':p['refs']+['cap-'+r for r in p['requirements']]})
        for rid in p['requirements']:
            targets['cap-'+rid].setdefault('refs',[]).append(p['id'])
    data['evidenceCount']=len(evidence['panels'])
    data['screenshotCount']=len(shots)
    data['evidenceBaseline']=evidence['baseline']
vendor_dir=OUT/'assets'/'vendor';vendor_dir.mkdir(parents=True,exist_ok=True)
if modern and (DATA/'tutorial-v3.json').exists():
    tutorial=json.loads((DATA/'tutorial-v3.json').read_text(encoding='utf-8'))
    destinations={n['id']:n for n in find_nodes(data['tree'])}
    for shot in tutorial['screenshots']:
        image_path=PRODUCT/shot['asset']
        assert image_path.resolve().is_relative_to((PRODUCT/'assets').resolve())
        assert hashlib.sha256(image_path.read_bytes()).hexdigest()==shot['sha256']
        shutil.copyfile(image_path,asset_dir/shot['file'])
        assert shot['target'] in destinations
        destinations[shot['target']]['implementation']=True
        destinations[shot['target']].setdefault('images',[]).append({
            'src':'assets/evidence/'+shot['file'],'title':shot['title'],'note':shot['note'],
            'originalSource':'当前源码界面 · 隔离示例数据 · 2026-09-06',
            'sha256':shot['sha256'],'width':shot['width'],'height':shot['height'],'callouts':shot['callouts']})
    data['tutorialCount']=len(tutorial['screenshots'])
    data['screenshotCount']+=data['tutorialCount']
for vendor in ('marked.min.js','purify.min.js','NOTICE.txt'):
    shutil.copyfile(TOOLS/'vendor'/vendor,vendor_dir/vendor)
if modern:
    # Internal adjudication history stays in source data, not public downloads.
    data.pop('requirementOverrides',None)
(OUT/'product-expanded.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node['children'])
nodes=list(walk(data['tree']))
lookup={node['id']:node for node in nodes}
assert len(lookup)==len(nodes)
for node in nodes:
    assert node['title'] and (node['body'] or node['children']), 'Leaf nodes need content; grouping nodes may omit filler prose'
    assert all(ref in lookup for ref in node.get('refs',[]))
for nid in data.get('mustTrace',[]):
    assert nid in lookup, f'mustTrace points at unknown node: {nid}'
    assert lookup[nid]['refs'], f'{nid} must trace back to a scenario/problem'
payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
template=(TOOLS/'templates'/'product.template.html').read_text(encoding='utf-8')
(OUT/'index.html').write_text(template.replace('__PRODUCT_JSON__',payload),encoding='utf-8')
lines=['---','tags: [产品定位, 需求设计, Agent可观测性]','date: 2026-09-05','---',
       '# 新产品定义与需求推导','',data['status'],'',data['position'],'',
       '> '+data['presentation']['note'],'',data['firstScenario'],'']
def md(nodes,depth=2):
    for node in nodes:
        lines.extend([f"{'#'*min(depth,6)} {node['title']}",'',f"<a id=\"{node['id']}\"></a>",'',node['body'],''])
        if node.get('basis'):
            lines.extend(['<details><summary>来源与设计依据</summary>','',node['basis'],'','</details>',''])
        if node.get('refs'):
            lines.extend(['关联依据：'+'；'.join(f"[{lookup[r]['title']}](#{r})" for r in node['refs']),''])
        for image in node.get('images',[]):
            lines.extend([f"![{image['title']}]({image['src']})",'',image['note'],'',f"原图来源：`{image['originalSource']}`。SHA-256：`{image['sha256']}`。",''])
            for number,callout in enumerate(image.get('callouts',[]),1):
                lines.extend([f"{number}. {callout['text']}",''])
        md(node['children'],depth+1)
md(data['tree'])
if modern:
    lines.extend(['## 持续维护','',data['presentation']['reading'],'',
                  '需求和设计：data/product-v3.json；新条目：data/gaps-v3.json；实现说明与代码证据：data/implementation-v3.json；截图：data/evidence/v3/。', '',
                  '存量截图只说明画面中已有的界面，不等同于当前版本实机验收。源码证据是固定快照；后续实现改变时显式更新证据并重新验证。'])
else:
    lines.extend(['## 本轮依据与尚待决定事项','',
              '用户已确认：从产品定位和主要功能开始梳理，再逐步扩展。首批人群、核心场景和首版范围仍是可修改提案。', '',
              '参考材料：旧版能力库 docs/product/data/capabilities.json（104 项）、原项目 docs/guides/同类工具构建手册.md 与 docs/development/开发约定.md；它们提供可行能力与证据约束，不证明目标用户有市场需求。', '',
              '下一步：先确认或修改首批用户与一句话定位，再用真实任务验证核心场景，最后决定哪些功能进入首版。'])
(OUT/'AI_产品定义与需求推导.md').write_text('\n'.join(lines),encoding='utf-8')
opml=ET.Element('opml',version='2.0')
head=ET.SubElement(opml,'head');ET.SubElement(head,'title').text=data['title']
root=ET.SubElement(ET.SubElement(opml,'body'),'outline',text=data['title'],_note=data['position'])
def outlines(parent,nodes):
    for node in nodes:
        out=ET.SubElement(parent,'outline',text=node['title'],id=node['id'])
        ET.SubElement(out,'outline',text=node['body'],kind='description')
        if node.get('basis'):
            ET.SubElement(out,'outline',text=node['basis'],kind='basis')
        if node.get('refs'):
            ET.SubElement(out,'outline',text='关联：'+'；'.join(lookup[r]['title'] for r in node['refs']),kind='references')
        for image in node.get('images',[]):
            ET.SubElement(out,'outline',text=image['title']+'：'+image['note'],url=image['src'],kind='image')
        outlines(out,node['children'])
outlines(root,data['tree']);ET.indent(opml,space='  ')
ET.ElementTree(opml).write(OUT/'AI_新产品需求导图.opml',encoding='utf-8',xml_declaration=True)
assert len(ET.parse(OUT/'AI_新产品需求导图.opml').findall('.//outline[@id]')) == len(nodes)
document=(OUT/'AI_产品定义与需求推导.md').read_text(encoding='utf-8')
assert all(document.count(f'<a id="{node["id"]}"></a>')==1 for node in nodes)
print(json.dumps({'version':VERSION,'gaps':len(gaps['items']),'review':data['reviewCounts'],'branches':len(data['tree']),'nodes':len(nodes),'evidence_panels':data['evidenceCount'],'catalog_items':len(mapped),'references':sum(len(n.get('refs',[])) for n in nodes)}))

if modern:
    from book_bundle import bundle
    print(json.dumps({"standalone":bundle(ROOT, OUT)}))
