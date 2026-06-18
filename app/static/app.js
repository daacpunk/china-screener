// Minimal client helpers. HTMX handles most interactivity.
function copyText(id){
  const el = document.getElementById(id);
  if(!el) return;
  const txt = el.innerText || el.textContent;
  navigator.clipboard.writeText(txt).then(()=>{
    const b = document.getElementById(id+'-copybtn');
    if(b){ const o=b.innerText; b.innerText='Copied!'; setTimeout(()=>b.innerText=o,1200); }
  });
}
