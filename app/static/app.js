// Minimal client helpers. HTMX handles most interactivity.

// Toggle the free-text custom-model input when "Other (custom)" is chosen.
function toggleCustomModel(sel){
  const form = sel.closest('form');
  if(!form) return;
  const custom = form.querySelector('.model-custom');
  if(!custom) return;
  if(sel.value === '__custom__'){ custom.style.display=''; custom.focus(); }
  else { custom.style.display='none'; }
}

function copyText(id){
  const el = document.getElementById(id);
  if(!el) return;
  const txt = el.innerText || el.textContent;
  navigator.clipboard.writeText(txt).then(()=>{
    const b = document.getElementById(id+'-copybtn');
    if(b){ const o=b.innerText; b.innerText='Copied!'; setTimeout(()=>b.innerText=o,1200); }
  });
}
