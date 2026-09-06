/* Portable assets, downloads and source archive. No network requests. */
window.BOOK=JSON.parse(document.getElementById('bookData').textContent);
const bookURLs=new Map();
window.bookAsset=function(path){
  if(!BOOK.files[path])return path;
  if(!bookURLs.has(path)){
    const f=BOOK.files[path], raw=atob(f.base64), bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
    bookURLs.set(path,URL.createObjectURL(new Blob([bytes],{type:f.mime})));
  }
  return bookURLs.get(path);
};
window.addEventListener('DOMContentLoaded',()=>{
  document.body.classList.add('wide-reader');
  const dialog=document.createElement('dialog');dialog.id='bookDialog';
  dialog.setAttribute('aria-labelledby','bookTitle');
  dialog.innerHTML='<div class="dialog-toolbar"><strong id="bookTitle">文档与依据</strong><button type="button" id="bookClose">关闭</button></div><label>选择文档 <select id="bookSelect" style="max-width:100%;font:inherit;padding:8px"></select></label><p id="bookNotice" class="note"></p><article id="bookText" class="body"></article>';
  document.body.append(dialog);
  const select=document.getElementById('bookSelect');
  for(const [key,doc] of Object.entries(BOOK.documents))select.add(new Option(doc.title,key));
  const showDoc=(key,hash)=>{
    select.value=key;const doc=BOOK.documents[key];
    document.getElementById('bookTitle').textContent=doc.title;
    document.getElementById('bookNotice').textContent=doc.notice;
    const content=document.getElementById('bookText');
    content.innerHTML=DOMPurify.sanitize(marked.parse(doc.text,{breaks:true}),{FORBID_TAGS:['img','iframe','style','script']});
    const headings=[...content.querySelectorAll('h2,h3')];
    headings.forEach((h,i)=>h.id='section-'+i);
    if(headings.length>8){
      const nav=document.createElement('details');nav.innerHTML='<summary>本篇目录（'+headings.length+' 节）</summary>';
      const list=document.createElement('ul');
      headings.forEach(h=>{const li=document.createElement('li'),a=document.createElement('a');a.textContent=h.textContent;a.href='#doc='+encodeURIComponent(key)+'&section='+h.id;li.append(a);list.append(li);});
      nav.append(list);content.prepend(nav);
    }
    if(!dialog.open)dialog.showModal();dialog.scrollTop=0;
    if(hash){const found=[...content.querySelectorAll('[id]')].find(x=>x.id===hash);if(found)found.scrollIntoView();}
  };
  select.onchange=()=>showDoc(select.value);
  document.getElementById('bookClose').onclick=()=>dialog.close();
  for(const a of document.querySelectorAll('.downloads a')){
    const raw=a.getAttribute('href');
    if(BOOK.files[raw]){a.href=bookAsset(raw);a.download=raw;}
  }
  const ref=document.querySelector('.reference');ref.textContent='阅读说明与开发参考';ref.setAttribute('href','#book-documents');
  const collaboration=document.createElement('button');
  collaboration.id='collaboration';collaboration.type='button';collaboration.textContent='三类文档与协作';
  collaboration.onclick=()=>showDoc('AI_三类文档与项目协作.md');
  document.querySelector('.toolbar').append(collaboration);
  document.getElementById('planningDocs').remove();
  document.getElementById('evidence').textContent='当前功能与截图';
  document.getElementById('buildNote').textContent='功能说明基线：v0.4.26 · 操作截图与历史示例分别标注 · 可通过目录、搜索与章节链接阅读。';
  const followHash=()=>{
    const raw=location.hash.slice(1);
    if(raw.startsWith('doc=')){const params=new URLSearchParams(raw),key=params.get('doc');if(BOOK.documents[key])showDoc(key,params.get('section'));return;}
    const id=decodeURIComponent(raw);if(index.has(id))go(id);
  };
  window.addEventListener('hashchange',followHash);followHash();
  document.addEventListener('click',e=>{
    const a=e.target.closest('a');if(!a)return;
    const raw=a.getAttribute('href')||'';
    if(raw==='#book-documents'){e.preventDefault();showDoc('AI_阅读说明.md');return;}
    const [path,hash]=raw.split('#');let name;
    if(!path && hash && typeof index!=='undefined' && index.has(hash)){
      e.preventDefault();if(dialog.open)dialog.close();go(hash);return;
    }
    try{name=decodeURIComponent(path.split('/').pop());}catch{return;}
    if(BOOK.documents[name]){e.preventDefault();showDoc(name,hash);return;}
    if(dialog.contains(a)&&path&&!/^(https?:|mailto:)/i.test(path)){
      e.preventDefault();document.getElementById('bookNotice').textContent='此路径是原始资料的定位信息，未作为独立文件打包；相关有效需求见本书正文。';
    }
  });
});
