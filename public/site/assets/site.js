document.documentElement.classList.add('js');
const viewer=document.getElementById('image-viewer');
if(viewer){
 const picture=viewer.querySelector('img'),caption=viewer.querySelector('.viewer-bar p');
 for(const link of document.querySelectorAll('[data-zoom]'))link.addEventListener('click',e=>{e.preventDefault();picture.src=link.href;picture.alt=link.querySelector('img').alt;caption.textContent=picture.alt;viewer.showModal();});
 viewer.querySelector('button').addEventListener('click',()=>viewer.close());
 viewer.addEventListener('click',e=>{if(e.target===viewer){const r=viewer.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)viewer.close();}});
}
const copy=document.querySelector('.copy-button');
if(copy)copy.addEventListener('click',async()=>{const text=document.getElementById('agent-request').innerText;try{await navigator.clipboard.writeText(text);copy.textContent=copy.dataset.done;}catch{const range=document.createRange();range.selectNodeContents(document.getElementById('agent-request'));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);copy.textContent=copy.dataset.fallback;}});
