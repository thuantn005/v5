/* configs_panel.js — panel "Bo suu tap Jackpot Config" cho dashboard v5.
   Gan vao index.html:  <div id="configs-panel"></div><script src="configs_panel.js"></script> */
(function () {
  function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
  function fmt(nums){return nums.map(n=>String(n).padStart(2,'0')).join(' ');}
  function render(host, d) {
    var rows = d.tickets.slice().sort(function(a,b){
      var la=Math.max.apply(null,a.history.map(h=>h.draw_id));
      var lb=Math.max.apply(null,b.history.map(h=>h.draw_id));
      return (a.type==='fixed')?-1:(b.type==='fixed')?1:lb-la;
    }).map(function(t){
      var hist=t.history.map(h=>'#'+h.draw_id+' ('+h.date+')').join('<br>');
      var ve=fmt(t.numbers)+(t.special?' | ĐB '+String(t.special).padStart(2,'0'):'');
      var name=t.type==='fixed'?'Vé cố định':'seed '+t.seed;
      return '<tr><td>'+esc(name)+'</td><td>'+hist+'</td><td><b>'+esc(ve)+'</b></td></tr>';
    }).join('');
    host.innerHTML =
      '<section style="margin:24px 0;padding:16px;border:1px solid #252e42;border-radius:12px;background:#181e2e">'+
      '<h2 style="margin-top:0;font-size:1rem;font-weight:700">🗂️ Bộ sưu tập Jackpot Config — vé kỳ #'+d.next_draw+'</h2>'+
      '<p style="font-size:.82em;color:#7a869e">⚠️ '+esc(d.disclaimer)+'</p>'+
      '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:.8rem">'+
      '<thead><tr>'+
      '<th style="text-align:left;padding:5px 8px;color:#7a869e;border-bottom:1px solid #252e42">Config</th>'+
      '<th style="text-align:left;padding:5px 8px;color:#7a869e;border-bottom:1px solid #252e42">Jackpot lịch sử</th>'+
      '<th style="text-align:left;padding:5px 8px;color:#7a869e;border-bottom:1px solid #252e42">Vé kỳ #'+d.next_draw+'</th>'+
      '</tr></thead>'+
      '<tbody>'+rows+'</tbody></table></div>'+
      '<p style="font-size:.75em;color:#7a869e;margin-top:8px">Sinh lúc '+esc(d.generated_at)+
      ' · tái tạo: <code style="background:#1e2738;border-radius:4px;padding:1px 5px">python scripts/gen_config_tickets.py</code></p></section>';
    var st=document.createElement('style');
    st.textContent='#configs-panel tbody td{border-bottom:1px solid #1e2534;padding:5px 8px;vertical-align:top;color:#e2e8f4}';
    document.head.appendChild(st);
  }
  function boot(){
    var host=document.getElementById('configs-panel');
    if(!host){host=document.createElement('div');host.id='configs-panel';document.body.appendChild(host);}
    fetch('config_tickets.json?t='+Date.now()).then(r=>r.json()).then(d=>render(host,d))
      .catch(e=>{host.innerHTML='<p style="color:#7a869e;font-size:.82em">Không tải được config_tickets.json ('+esc(String(e))+')</p>';});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
