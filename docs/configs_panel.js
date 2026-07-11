/* configs_panel.js — panel "Bo suu tap Jackpot Config" cho dashboard v5. */
(function () {
  function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
  function fmt(nums){return nums.map(n=>String(n).padStart(2,'0')).join(' ');}

  function hitBadge(hits) {
    if (hits >= 3) return '<span style="background:#166534;color:#bbf7d0;border-radius:4px;padding:1px 6px;font-weight:700">'+hits+' khớp 🎯</span>';
    if (hits === 2) return '<span style="background:#1e3a5f;color:#93c5fd;border-radius:4px;padding:1px 6px">'+hits+' khớp</span>';
    if (hits === 1) return '<span style="color:#7a869e">'+hits+' khớp</span>';
    return '<span style="color:#4a5568">0 khớp</span>';
  }

  function renderLastResult(lr, prevDraw) {
    if (!lr) return '<span style="color:#4a5568">—</span>';
    var actual = fmt(lr.actual);
    var predicted = fmt(lr.predicted);
    var hits = lr.main_hits;
    var spHit = lr.special_hit;
    var dbStr = lr.actual_special ? ' ĐB<b style="color:'+(spHit?'#fbbf24':'#4a5568')+'">'+String(lr.actual_special).padStart(2,'0')+'</b>' : '';

    // Highlight số khớp trong actual
    var actualSet = new Set(lr.actual);
    var predSet = new Set(lr.predicted);
    var actualHtml = lr.actual.map(function(n){
      var hit = predSet.has(n);
      return '<span style="'+(hit?'color:#34d399;font-weight:700':'color:#e2e8f4')+'">'
        +String(n).padStart(2,'0')+'</span>';
    }).join(' ');

    return '<div style="font-size:.78rem;line-height:1.7">'
      +'<div style="color:#7a869e">kỳ #'+lr.draw_id+' ('+lr.draw_date+')</div>'
      +'<div>Thực tế: '+actualHtml+dbStr+'</div>'
      +'<div>Dự đoán: <span style="color:#7a869e">'+predicted
      +(spHit?' <span style="color:#fbbf24">ĐB✓</span>':'')+'</span></div>'
      +'<div>'+hitBadge(hits)+'</div>'
      +'</div>';
  }

  function render(host, d) {
    var prevDraw = d.prev_draw;

    var rows = d.tickets.slice().sort(function(a,b){
      // Sort: nhiều hits nhất trước, rồi theo jackpot history mới nhất
      var ha = a.last_result ? a.last_result.main_hits : -1;
      var hb = b.last_result ? b.last_result.main_hits : -1;
      if (hb !== ha) return hb - ha;
      var la=Math.max.apply(null,a.history.map(function(h){return h.draw_id;}));
      var lb=Math.max.apply(null,b.history.map(function(h){return h.draw_id;}));
      return (a.type==='fixed')?-1:(b.type==='fixed')?1:lb-la;
    }).map(function(t){
      var hist=t.history.map(function(h){return '#'+h.draw_id+' ('+h.date+')';}).join('<br>');
      var ve=fmt(t.numbers)+(t.special?' | ĐB '+String(t.special).padStart(2,'0'):'');
      var name=t.type==='fixed'?'Vé cố định':'seed '+t.seed;
      return '<tr>'
        +'<td>'+esc(name)+'</td>'
        +'<td>'+hist+'</td>'
        +'<td>'+renderLastResult(t.last_result, prevDraw)+'</td>'
        +'<td><b>'+esc(ve)+'</b></td>'
        +'</tr>';
    }).join('');

    host.innerHTML =
      '<section style="margin:24px 0;padding:16px;border:1px solid #252e42;border-radius:12px;background:#181e2e">'+
      '<h2 style="margin-top:0;font-size:1rem;font-weight:700">🗂️ Bộ sưu tập Jackpot Config — vé kỳ #'+d.next_draw+'</h2>'+
      '<p style="font-size:.82em;color:#7a869e">⚠️ '+esc(d.disclaimer)+'</p>'+
      '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:.8rem">'+
      '<thead><tr>'+
      '<th style="text-align:left;padding:5px 8px;color:#7a869e;border-bottom:1px solid #252e42;white-space:nowrap">Config</th>'+
      '<th style="text-align:left;padding:5px 8px;color:#7a869e;border-bottom:1px solid #252e42;white-space:nowrap">Jackpot lịch sử</th>'+
      '<th style="text-align:left;padding:5px 8px;color:#7a869e;border-bottom:1px solid #252e42;white-space:nowrap">Kỳ #'+prevDraw+' (vừa quay)</th>'+
      '<th style="text-align:left;padding:5px 8px;color:#7a869e;border-bottom:1px solid #252e42;white-space:nowrap">Vé kỳ #'+d.next_draw+'</th>'+
      '</tr></thead>'+
      '<tbody>'+rows+'</tbody></table></div>'+
      '<p style="font-size:.75em;color:#7a869e;margin-top:8px">Sinh lúc '+esc(d.generated_at)+
      ' · tái tạo: <code style="background:#1e2738;border-radius:4px;padding:1px 5px">python scripts/gen_config_tickets.py</code></p></section>';
    var st=document.createElement('style');
    st.textContent='#configs-panel tbody td{border-bottom:1px solid #1e2534;padding:6px 8px;vertical-align:top;color:#e2e8f4}';
    document.head.appendChild(st);
  }

  function boot(){
    var host=document.getElementById('configs-panel');
    if(!host){host=document.createElement('div');host.id='configs-panel';document.body.appendChild(host);}
    fetch('config_tickets.json?t='+Date.now()).then(function(r){return r.json();}).then(function(d){render(host,d);})
      .catch(function(e){host.innerHTML='<p style="color:#7a869e;font-size:.82em">Không tải được config_tickets.json ('+esc(String(e))+')</p>';});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
