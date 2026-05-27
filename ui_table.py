# """
# ui_table.py — GAS-style rich creator results table for Streamlit
# Renders as an HTML component: profile pic, all contact fields, video link, quality badge.
# """

# from __future__ import annotations
# import json
# import streamlit.components.v1 as components

# # ─── HTML/CSS/JS TEMPLATE ───────────────────────────────────────────────────
# _TABLE_TEMPLATE = r"""
# <!DOCTYPE html>
# <html>
# <head>
# <meta charset="UTF-8">
# <style>
# :root {
#   --bg: #ffffff;
#   --surface: #f5f5f5;
#   --card: #f0f0f0;
#   --border: #e0e0e0;
#   --border-dark: #cccccc;
#   --accent: #0a0a0a;
#   --green: #1a7a3a;
#   --yellow: #7a4a00;
#   --red: #8a0000;
#   --text: #0a0a0a;
#   --muted: #555555;
#   --dim: #888888;
#   --font: 'League Spartan', sans-serif;
#   --mono: 'JetBrains Mono', monospace;
# }
# @import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@400;600;700;800&display=swap');
# * { margin: 0; padding: 0; box-sizing: border-box; }
# body { font-family: var(--font); background: var(--bg); color: var(--text); font-size: 12px; }

# /* Toolbar */
# #toolbar {
#   display: flex; align-items: center; gap: 10px; padding: 8px 14px;
#   background: var(--surface); border-bottom: 1px solid var(--border);
#   flex-wrap: wrap; font-size: 11px; position: sticky; top: 0; z-index: 20;
#   font-family: var(--font);
# }
# #toolbar select {
#   background: var(--bg); border: 1px solid var(--border-dark); border-radius: 4px;
#   padding: 5px 8px; color: var(--text); font-size: 11px; cursor: pointer;
#   font-family: var(--font); font-weight: 600;
# }
# #toolbar button {
#   background: var(--bg); border: 1px solid var(--border-dark); padding: 5px 12px;
#   border-radius: 4px; color: var(--text); cursor: pointer; font-size: 11px;
#   font-family: var(--font); font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
#   transition: background .15s, color .15s;
# }
# #toolbar button:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
# #toolbar button:disabled { opacity: .35; cursor: not-allowed; }
# #csvBtn { background: var(--accent); color: #fff; border-color: var(--accent); }
# #csvBtn:hover { background: #333; border-color: #333; }
# .sep { color: var(--border-dark); font-size: 14px; }

# /* Table */
# .tbl-wrap { overflow-x: auto; overflow-y: auto; max-height: calc(100vh - 60px); }
# table {
#   width: max-content; min-width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px;
#   font-family: var(--font);
# }
# thead th {
#   background: var(--surface); color: var(--dim); font-size: 10px; font-weight: 700;
#   text-transform: uppercase; letter-spacing: 0.06em; padding: 10px 12px;
#   border-bottom: 2px solid var(--accent); position: sticky; top: 0; z-index: 12;
#   white-space: nowrap; font-family: var(--font);
# }
# tbody td {
#   padding: 9px 12px; border-bottom: 1px solid var(--border);
#   white-space: nowrap; vertical-align: middle; font-family: var(--font);
# }
# tbody tr:hover td { background: var(--surface); }
# tbody tr.sel td { background: rgba(0,0,0,.04); }

# /* Sticky cols */
# thead th:nth-child(1), tbody td:nth-child(1) { position: sticky; left: 0; z-index: 11; width: 36px; background: var(--bg); }
# thead th:nth-child(2), tbody td:nth-child(2) { position: sticky; left: 36px; z-index: 11; width: 44px; background: var(--bg); }
# thead th:nth-child(3), tbody td:nth-child(3) {
#   position: sticky; left: 80px; z-index: 11; min-width: 200px;
#   border-right: 2px solid var(--border); background: var(--bg);
#   box-shadow: 2px 0 8px rgba(0,0,0,.06);
# }
# thead th:nth-child(1), thead th:nth-child(2), thead th:nth-child(3) { z-index: 13; background: var(--surface); }

# /* Cell styles */
# .pcell { display: flex; align-items: center; gap: 9px; }
# .pcell img { width: 30px; height: 30px; border-radius: 50%; object-fit: cover; flex-shrink: 0; border: 1px solid var(--border); }
# .pfallback { width: 30px; height: 30px; border-radius: 50%; background: var(--card); display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 800; letter-spacing: .05em; color: #555; text-transform: uppercase; flex-shrink: 0; border: 1px solid var(--border); font-family: var(--font); }
# .pname a { color: var(--text); font-weight: 700; text-decoration: none; font-size: 12px; }
# .pname a:hover { text-decoration: underline; }
# .phandle { font-size: 10px; color: var(--muted); margin-top: 1px; font-weight: 500; }
# .num { font-family: var(--mono); text-align: right; }
# .dim { color: var(--muted); }
# .nc { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
# .vtc { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
# .vtc a { color: var(--accent); text-decoration: none; font-size: 11px; font-weight: 600; }
# .vtc a:hover { text-decoration: underline; }
# .vdate { font-size: 9px; color: var(--dim); margin-top: 1px; }
# .lc a { color: var(--accent); text-decoration: none; font-weight: 600; font-size: 11px; }
# .lc a:hover { text-decoration: underline; }

# /* Badges */
# .badge { padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700; display: inline-block; font-family: var(--font); letter-spacing: 0.03em; text-transform: uppercase; }
# .b-blue   { background: var(--surface); color: var(--text); border: 1px solid var(--border-dark); }
# .b-green  { background: var(--green); color: #fff; }
# .b-yellow { background: var(--yellow); color: #fff; }
# .b-red    { background: var(--red); color: #fff; }
# .b-purple { background: #333; color: #fff; }
# .b-match-high { background: #0a0a0a; color: #fff; border: 1px solid #0a0a0a; }
# .b-match-mid  { background: #fff; color: #444; border: 1px solid #ccc; }
# .b-match-low  { background: #fff; color: #aaa; border: 1px solid #e0e0e0; }
# .gv { color: var(--green); font-weight: 700; }
# .gs { color: var(--yellow); font-weight: 700; }

# /* Plt badge text labels */
# .plt-ig { font-family: var(--font); font-size: 9px; font-weight: 800; letter-spacing: .05em; color: #555; text-transform: uppercase; }
# .plt-yt { font-family: var(--font); font-size: 9px; font-weight: 800; letter-spacing: .05em; color: #555; text-transform: uppercase; }

# /* Empty state */
# .empty { padding: 40px; text-align: center; color: var(--muted); font-size: 14px; font-family: var(--font); font-weight: 600; }

# /* Checkbox */
# input[type="checkbox"] { accent-color: #0a0a0a; cursor: pointer; }
# </style>
# </head>
# <body>
# <div id="toolbar">
#   <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
#     <input type="checkbox" id="selAll" onchange="toggleAll(this)"> All
#   </label>
#   <span class="sep">|</span>
#   <span>Showing <b id="totN">0</b> · <b id="selN">0</b> selected</span>
#   <span class="sep">|</span>
#   <select id="sortSel" onchange="applySort()">
#     <option value="ai_desc">AI Score ↓</option>
#     <option value="quality_desc">Quality ↓</option>
#     <option value="subs_desc">Followers ↓</option>
#     <option value="subs_asc">Followers ↑</option>
#     <option value="match">Match Status</option>
#   </select>
#   <select id="filterSel" onchange="applySort()">
#     <option value="all">All statuses</option>
#     <option value="high">High only</option>
#     <option value="high_mid">High + Mid</option>
#   </select>
#   <button id="csvBtn" onclick="downloadCSV()">&#x21E9; Download CSV</button>
# </div>

# <div class="tbl-wrap">
#   <table id="tbl">
#     <thead>
#       <tr>
#         <th></th>
#         <th>Plt</th>
#         <th>Creator</th>
#         <th>Match</th>
#         <th>AI</th>
#         <th>Quality</th>
#         <th>Gender</th>
#         <th>Followers</th>
#         <th>Country</th>
#         <th>Total Views</th>
#         <th>Videos</th>
#         <th>Created</th>
#         <th>Niche</th>
#         <th>Email</th>
#         <th>Phone</th>
#         <th>Instagram</th>
#         <th>Website</th>
#         <th>Latest Content</th>
#         <th>Vid Views</th>
#         <th>Vid Likes</th>
#         <th>Vid Cmts</th>
#         <th>Evidence / Source</th>
#         <th>Reason</th>
#       </tr>
#     </thead>
#     <tbody id="tbody"></tbody>
#   </table>
# </div>

# <script>
# const ALL_CREATORS = __DATA__;
# let displayOrder = [];
# let selected = new Set();

# function fmt(n){
#   n=parseInt(n);
#   if(isNaN(n)||n===0)return'—';
#   if(n>=1e9)return(n/1e9).toFixed(2)+'B';
#   if(n>=1e6)return(n/1e6).toFixed(2)+'M';
#   if(n>=1e3)return(n/1e3).toFixed(1)+'K';
#   return n.toLocaleString();
# }
# function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
# function ce(v){var s=String(v===null||v===undefined?'':v);if(s.search(/("|,|\n)/)>=0)return'"'+s.replace(/"/g,'""')+'"';return s}
# function td(v,cls){return'<td class="'+(cls||'dim')+'">'+esc(v||'—')+'</td>'}
# function tn(v,cls){var n=parseInt(v);return'<td class="num '+(cls||'')+'">'+(isNaN(n)||v===''||v===null||v===undefined?'<span style="color:#2a3142">—</span>':fmt(n))+'</td>'}
# function tl(url,label,cls){if(!url)return'<td class="dim">—</td>';return'<td class="lc '+(cls||'')+'"><a href="'+esc(url)+'" target="_blank">'+esc(label||url)+'</a></td>'}

# function getCreatorFields(c){
#   const isIG = c.platform === 'instagram';
#   return {
#     isIG,
#     name:    isIG ? (c.full_name||c.username||'') : (c.channel_name||''),
#     handle:  isIG ? ('@'+(c.username||'')) : (c.handle||''),
#     url:     isIG ? (c.profile_url||'') : (c.handle_url||c.channel_url||''),
#     subs:    isIG ? (c.followers||0) : (c.subscribers||0),
#     thumb:   c.thumbnail||'',
#     quality: isIG ? Math.round(c.local_match_score||0) : (c._quality_score||0),
#     gender:  isIG ? _igGender(c) : (c._gender_label||'unknown'),
#     country: c.country||'',
#     views:   isIG ? '' : (c.total_views||0),
#     vids:    isIG ? (c.posts_count||'') : (c.video_count||''),
#     created: isIG ? '' : (c.channel_created||''),
#     niche:   isIG ? (c.source_hashtag||c.genre_match||'') : (c.description||'').substring(0,30),
#     email:   c.email||'',
#     phone:   c.phone||'',
#     ig:      isIG ? c.profile_url : (c.instagram_url||''),
#     website: isIG ? (c.external_url||'') : (c.website||c.aggregator_url||''),
#     vtitle:  isIG ? 'Sample post' : (c.video_title||''),
#     vurl:    isIG ? (c.sample_post_url||'') : (c.video_url||''),
#     vdate:   isIG ? '' : (c.video_published||''),
#     vviews:  isIG ? '' : (c.video_views||''),
#     vlikes:  isIG ? '' : (c.video_likes||''),
#     vcmts:   isIG ? '' : (c.video_comments||''),
#     match:   c.match_status||'review',
#     ai:      c.ai_score,
#     evidence:isIG ? (c.evidence||c.source_hashtag||'') : (c._creator_evidence||c.video_title||''),
#     reason:  c.reject_reason||c.review_reason||c.ai_reason||'',
#   };
# }

# function _igGender(c){
#   const gc = c.gender_confidence||0;
#   if(gc>60) return 'male';
#   return 'unknown';
# }

# function matchCls(s){
#   if(s==='high')   return 'b-match-high';
#   if(s==='review'||s==='mid') return 'b-match-mid';
#   return 'b-match-low';
# }
# function matchLabel(s){
#   if(s==='high')   return 'High';
#   if(s==='review'||s==='mid') return 'Mid';
#   return 'Low';
# }
# function genderIcon(g){
#   if(g==='male')   return '<span style="font-family:var(--font);font-size:9px;font-weight:800;color:#555;text-transform:uppercase">M</span>';
#   if(g==='female') return '<span style="font-family:var(--font);font-size:9px;font-weight:800;color:#555;text-transform:uppercase">F</span>';
#   return '<span style="font-family:var(--font);font-size:9px;font-weight:600;color:#aaa;text-transform:uppercase">—</span>';
# }
# function qualityCls(q){
#   if(q>=70) return 'b-green';
#   if(q>=45) return 'b-yellow';
#   return 'b-red';
# }

# function renderTable(){
#   const tbody = document.getElementById('tbody');
#   const totN  = document.getElementById('totN');
#   tbody.innerHTML='';

#   const filterSel = document.getElementById('filterSel').value;
#   let visible = displayOrder.filter(i=>{
#     const m = ALL_CREATORS[i].match_status||'review';
#     if(filterSel==='high') return m==='high';
#     if(filterSel==='high_mid') return m==='high'||m==='review'||m==='mid';
#     return true;
#   });

#   totN.textContent=visible.length;

#   if(!visible.length){
#     tbody.innerHTML='<tr><td colspan="23" class="empty">No creators match the current filter.</td></tr>';
#     return;
#   }

#   visible.forEach(ci=>{
#     const c = ALL_CREATORS[ci];
#     const f = getCreatorFields(c);
#     const tr = document.createElement('tr');
#     tr.id='tr'+ci;

#     const thumb = f.thumb
#       ? '<img src="'+esc(f.thumb)+'" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'" alt="">'
#         +'<span class="pfallback" style="display:none">'+(f.isIG?'IG':'YT')+'</span>'
#       : '<span class="pfallback">'+(f.isIG?'IG':'YT')+'</span>';

#     const nameCell =
#       '<div class="pcell">'+thumb+
#       '<div><div class="pname"><a href="'+esc(f.url)+'" target="_blank">'+esc(f.name)+'</a></div>'+
#       '<div class="phandle">'+esc(f.handle)+'</div></div></div>';

#     const videoCell = f.vurl
#       ? '<td class="vtc"><a href="'+esc(f.vurl)+'" target="_blank">'+esc((f.vtitle||'View').substring(0,40))+'</a>'+
#         (f.vdate?'<div class="vdate">'+esc(f.vdate)+'</div>':'')+'</td>'
#       : '<td class="dim">—</td>';

#     const igHandle = f.ig ? (f.ig.replace(/\/$/, '').split('/').pop() || f.ig) : '';

#     const aiCell = (f.ai!==null&&f.ai!==undefined&&f.ai!=='')
#       ? '<td><span class="badge '+qualityCls(parseFloat(f.ai)*10)+'">'+f.ai+'/10</span></td>'
#       : '<td class="dim">—</td>';

#     tr.innerHTML =
#       '<td style="text-align:center"><input type="checkbox" id="ck'+ci+'" onchange="chk('+ci+')"></td>'+
#       '<td style="text-align:center" title="'+(f.isIG?'Instagram':'YouTube')+'"><span class="'+(f.isIG?'plt-ig':'plt-yt')+'">'+(f.isIG?'IG':'YT')+'</span></td>'+
#       '<td>'+nameCell+'</td>'+
#       '<td><span class="badge '+matchCls(f.match)+'">'+matchLabel(f.match)+'</span></td>'+
#       aiCell+
#       '<td><span class="badge '+qualityCls(f.quality)+'">'+f.quality+'</span></td>'+
#       '<td style="text-align:center;font-size:13px">'+genderIcon(f.gender)+'</td>'+
#       '<td><span class="badge b-blue">'+fmt(f.subs)+'</span></td>'+
#       td(f.country||'—')+
#       tn(f.views)+
#       td(f.vids||'—')+
#       td(f.created||'—')+
#       '<td class="nc dim" title="'+esc(f.niche)+'">'+esc((f.niche||'—').substring(0,25))+'</td>'+
#       (f.email?'<td class="lc"><a href="mailto:'+esc(f.email)+'">'+esc(f.email)+'</a></td>':'<td class="dim">—</td>')+
#       td(f.phone||'—')+
#       (f.ig&&igHandle?tl(f.ig,'@'+igHandle):'<td class="dim">—</td>')+
#       (f.website?tl(f.website, f.website.replace(/^https?:\/\/(www\.)?/,'').substring(0,22)):'<td class="dim">—</td>')+
#       videoCell+
#       tn(f.vviews,'gv')+tn(f.vlikes,'gv')+tn(f.vcmts,'gv')+
#       '<td class="nc dim" title="'+esc(f.evidence)+'">'+esc((f.evidence||'—').substring(0,35))+'</td>'+
#       '<td class="nc dim" title="'+esc(f.reason)+'">'+esc((f.reason||'—').substring(0,40))+'</td>';

#     tr.onclick=e=>{if(e.target.tagName!=='INPUT'&&e.target.tagName!=='A')toggle(ci)};
#     tbody.appendChild(tr);
#   });
#   updCnt();
# }

# function buildDisplayOrder(){
#   displayOrder=ALL_CREATORS.map((_,i)=>i);
#   applySort(false);
# }

# function applySort(doRender=true){
#   const v=document.getElementById('sortSel').value;
#   displayOrder.sort((a,b)=>{
#     const ca=ALL_CREATORS[a], cb=ALL_CREATORS[b];
#     if(v==='ai_desc'){
#       const sa=parseFloat(ca.ai_score)||0, sb=parseFloat(cb.ai_score)||0;
#       return sb-sa;
#     }
#     if(v==='quality_desc'){
#       const qa=ca.platform==='instagram'?(ca.local_match_score||0):(ca._quality_score||0);
#       const qb=cb.platform==='instagram'?(cb.local_match_score||0):(cb._quality_score||0);
#       return qb-qa;
#     }
#     if(v==='subs_desc'){
#       const sa=parseInt(ca.platform==='instagram'?ca.followers:ca.subscribers)||0;
#       const sb=parseInt(cb.platform==='instagram'?cb.followers:cb.subscribers)||0;
#       return sb-sa;
#     }
#     if(v==='subs_asc'){
#       const sa=parseInt(ca.platform==='instagram'?ca.followers:ca.subscribers)||0;
#       const sb=parseInt(cb.platform==='instagram'?cb.followers:cb.subscribers)||0;
#       return sa-sb;
#     }
#     if(v==='match'){
#       const order={high:0,review:1,mid:1,rejected:2,low:2};
#       return (order[ca.match_status]||1)-(order[cb.match_status]||1);
#     }
#     return 0;
#   });
#   if(doRender) renderTable();
# }

# function toggle(i){const ck=document.getElementById('ck'+i);if(ck){ck.checked=!ck.checked;chk(i);}}
# function chk(i){
#   const ck=document.getElementById('ck'+i),tr=document.getElementById('tr'+i);
#   if(ck&&tr){ck.checked?(selected.add(i),tr.classList.add('sel')):(selected.delete(i),tr.classList.remove('sel'));}
#   updCnt();
# }
# function toggleAll(el){
#   displayOrder.forEach(i=>{
#     const ck=document.getElementById('ck'+i),tr=document.getElementById('tr'+i);
#     if(ck&&tr){ck.checked=el.checked;el.checked?(selected.add(i),tr.classList.add('sel')):(selected.delete(i),tr.classList.remove('sel'));}
#   });
#   updCnt();
# }
# function updCnt(){
#   document.getElementById('selN').textContent=selected.size;
#   document.getElementById('csvBtn').disabled=ALL_CREATORS.length===0;
# }

# function downloadCSV(){
#   const idxs=selected.size>0?Array.from(selected):displayOrder;
#   const rows=idxs.map(i=>ALL_CREATORS[i]);
#   const headers=['Platform','Name','Handle','URL','Followers','Country','Total Views','Videos',
#     'Created','Niche','Email','Phone','Instagram','Website','Latest Content URL',
#     'Latest Content Title','Publish Date','Vid Views','Vid Likes','Vid Comments',
#     'Match Status','AI Score','Quality Score','Evidence','Reason'];
#   const lines=[headers.map(ce).join(',')];
#   rows.forEach(c=>{
#     const f=getCreatorFields(c);
#     lines.push([
#       f.isIG?'Instagram':'YouTube',f.name,f.handle,f.url,f.subs,f.country,
#       f.views,f.vids,f.created,f.niche,f.email,f.phone,f.ig,f.website,
#       f.vurl,f.vtitle,f.vdate,f.vviews,f.vlikes,f.vcmts,
#       c.match_status||'',c.ai_score||'',f.quality,f.evidence,f.reason
#     ].map(ce).join(','));
#   });
#   const blob=new Blob(['\uFEFF'+lines.join('\n')],{type:'text/csv;charset=utf-8;'});
#   const a=document.createElement('a');
#   a.href=URL.createObjectURL(blob);
#   a.download='creators_'+new Date().toISOString().substring(0,10)+'.csv';
#   a.click();
# }

# // Init
# buildDisplayOrder();
# renderTable();
# </script>
# </body>
# </html>
# """.strip()


# def render_creator_table(creators: list[dict], height: int = 700) -> None:
#     """Render creators in a GAS-style rich HTML table with thumbnails, links, all fields."""
#     if not creators:
#         return
#     data_json = json.dumps(creators, default=str)
#     html = _TABLE_TEMPLATE.replace("__DATA__", data_json)
#     components.html(html, height=height, scrolling=True)

"""
ui_table.py — GAS-style rich creator results table for Streamlit
Renders as an HTML component: profile pic, all contact fields, video link, quality badge.
"""

from __future__ import annotations
import json
import streamlit.components.v1 as components

# ─── HTML/CSS/JS TEMPLATE ───────────────────────────────────────────────────
_TABLE_TEMPLATE = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
:root {
  --bg: #ffffff;
  --surface: #f9f9f8;
  --card: #f0f0ef;
  --border: #ebebeb;
  --border-dark: #d8d8d8;
  --accent: #111111;
  --green: #1a7a3a;
  --yellow: #7a4a00;
  --red: #8a0000;
  --text: #111111;
  --muted: #555555;
  --dim: #999999;
  --font: 'League Spartan', sans-serif;
  --mono: 'JetBrains Mono', monospace;
}
@import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@400;600;700;800&display=swap');
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: var(--font); background: var(--bg); color: var(--text); font-size: 12px; }

/* Toolbar */
#toolbar {
  display: flex; align-items: center; gap: 10px; padding: 8px 14px;
  background: var(--surface); border-bottom: 1px solid var(--border);
  flex-wrap: wrap; font-size: 11px; position: sticky; top: 0; z-index: 20;
  font-family: var(--font);
}
#toolbar select {
  background: var(--bg); border: 1px solid var(--border-dark); border-radius: 4px;
  padding: 5px 8px; color: var(--text); font-size: 11px; cursor: pointer;
  font-family: var(--font); font-weight: 600;
}
#toolbar button {
  background: var(--bg); border: 1px solid var(--border-dark); padding: 5px 12px;
  border-radius: 4px; color: var(--text); cursor: pointer; font-size: 11px;
  font-family: var(--font); font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  transition: background .15s, color .15s;
}
#toolbar button:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
#toolbar button:disabled { opacity: .35; cursor: not-allowed; }
#csvBtn { background: var(--accent); color: #fff; border-color: var(--accent); }
#csvBtn:hover { background: #333; border-color: #333; }
.sep { color: var(--border-dark); font-size: 14px; }

/* Table */
.tbl-wrap { overflow-x: auto; overflow-y: auto; max-height: calc(100vh - 60px); }
table {
  width: max-content; min-width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px;
  font-family: var(--font);
}
thead th {
  background: var(--surface); color: var(--dim); font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.06em; padding: 10px 12px;
  border-bottom: 2px solid var(--accent); position: sticky; top: 0; z-index: 12;
  white-space: nowrap; font-family: var(--font);
}
tbody td {
  padding: 9px 12px; border-bottom: 1px solid var(--border);
  white-space: nowrap; vertical-align: middle; font-family: var(--font);
}
tbody tr:hover td { background: var(--surface); }
tbody tr.sel td { background: rgba(0,0,0,.04); }

/* Sticky cols */
thead th:nth-child(1), tbody td:nth-child(1) { position: sticky; left: 0; z-index: 11; width: 36px; background: var(--bg); }
thead th:nth-child(2), tbody td:nth-child(2) { position: sticky; left: 36px; z-index: 11; width: 44px; background: var(--bg); }
thead th:nth-child(3), tbody td:nth-child(3) {
  position: sticky; left: 80px; z-index: 11; min-width: 200px;
  border-right: 2px solid var(--border); background: var(--bg);
  box-shadow: 2px 0 8px rgba(0,0,0,.06);
}
thead th:nth-child(1), thead th:nth-child(2), thead th:nth-child(3) { z-index: 13; background: var(--surface); }

/* Cell styles */
.pcell { display: flex; align-items: center; gap: 9px; }
.pcell img { width: 34px; height: 34px; border-radius: 50%; object-fit: cover; flex-shrink: 0; border: 1.5px solid var(--border); }
.pfallback { width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 800; letter-spacing: .04em; color: #fff; text-transform: uppercase; flex-shrink: 0; font-family: var(--font); }
.pname a { color: var(--text); font-weight: 700; text-decoration: none; font-size: 12px; }
.pname a:hover { text-decoration: underline; }
.phandle { font-size: 10px; color: var(--muted); margin-top: 1px; font-weight: 500; }
.num { font-family: var(--mono); text-align: right; }
.dim { color: var(--muted); }
.nc { max-width: 160px; overflow: hidden; text-overflow: ellipsis; }
.vtc { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.vtc a { color: var(--accent); text-decoration: none; font-size: 11px; font-weight: 600; }
.vtc a:hover { text-decoration: underline; }
.vdate { font-size: 9px; color: var(--dim); margin-top: 1px; }
.lc a { color: var(--accent); text-decoration: none; font-weight: 600; font-size: 11px; }
.lc a:hover { text-decoration: underline; }

/* Badges */
.badge { padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700; display: inline-block; font-family: var(--font); letter-spacing: 0.03em; text-transform: uppercase; }
.b-blue   { background: var(--surface); color: var(--text); border: 1px solid var(--border-dark); }
.b-green  { background: var(--green); color: #fff; }
.b-yellow { background: var(--yellow); color: #fff; }
.b-red    { background: var(--red); color: #fff; }
.b-purple { background: #333; color: #fff; }
.b-match-high { background: #0a0a0a; color: #fff; border: 1px solid #0a0a0a; }
.b-match-mid  { background: #fff; color: #444; border: 1px solid #ccc; }
.b-match-low  { background: #fff; color: #aaa; border: 1px solid #e0e0e0; }
.gv { color: var(--green); font-weight: 700; }
.gs { color: var(--yellow); font-weight: 700; }

/* Plt badge text labels */
.plt-ig { font-family: var(--font); font-size: 9px; font-weight: 800; letter-spacing: .05em; color: #555; text-transform: uppercase; }
.plt-yt { font-family: var(--font); font-size: 9px; font-weight: 800; letter-spacing: .05em; color: #555; text-transform: uppercase; }

/* Empty state */
.empty { padding: 40px; text-align: center; color: var(--muted); font-size: 14px; font-family: var(--font); font-weight: 600; }

/* Checkbox */
input[type="checkbox"] { accent-color: #0a0a0a; cursor: pointer; }
</style>
</head>
<body>
<div id="toolbar">
  <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
    <input type="checkbox" id="selAll" onchange="toggleAll(this)"> All
  </label>
  <span class="sep">|</span>
  <span>Showing <b id="totN">0</b> · <b id="selN">0</b> selected</span>
  <span class="sep">|</span>
  <select id="sortSel" onchange="applySort()">
    <option value="ai_desc">AI Score ↓</option>
    <option value="quality_desc">Quality ↓</option>
    <option value="subs_desc">Followers ↓</option>
    <option value="subs_asc">Followers ↑</option>
    <option value="match">Match Status</option>
  </select>
  <select id="filterSel" onchange="applySort()">
    <option value="all">All statuses</option>
    <option value="high">High only</option>
    <option value="high_mid">High + Mid</option>
  </select>
  <button id="csvBtn" onclick="downloadCSV()">&#x21E9; Download CSV</button>
</div>

<div class="tbl-wrap">
  <table id="tbl">
    <thead>
      <tr>
        <th></th>
        <th>Plt</th>
        <th>Creator</th>
        <th>Match</th>
        <th>AI</th>
        <th>Quality</th>
        <th>Gender</th>
        <th>Followers</th>
        <th>Country</th>
        <th>Total Views</th>
        <th>Videos</th>
        <th>Created</th>
        <th>Niche</th>
        <th>Email</th>
        <th>Phone</th>
        <th>Instagram</th>
        <th>Website</th>
        <th>Latest Content</th>
        <th>Vid Views</th>
        <th>Vid Likes</th>
        <th>Vid Cmts</th>
        <th>Evidence / Source</th>
        <th>Reason</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
const ALL_CREATORS = __DATA__;
let displayOrder = [];
let selected = new Set();

// Avatar color palette — professional, muted tones
const AVATAR_COLORS = [
  '#2D6A4F','#1B4332','#40916C','#52B788',
  '#264653','#2A9D8F','#457B9D','#1D3557',
  '#6B4226','#8B5E3C','#7B2D8B','#5A189A',
  '#9D0208','#6A0572','#343A40','#495057',
  '#0077B6','#023E8A','#7B3F00','#3D405B',
];

function avatarColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) { h = (h * 31 + name.charCodeAt(i)) & 0xffffffff; }
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
}

function avatarInitials(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function fmt(n){
  n=parseInt(n);
  if(isNaN(n)||n===0)return'—';
  if(n>=1e9)return(n/1e9).toFixed(2)+'B';
  if(n>=1e6)return(n/1e6).toFixed(2)+'M';
  if(n>=1e3)return(n/1e3).toFixed(1)+'K';
  return n.toLocaleString();
}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function ce(v){var s=String(v===null||v===undefined?'':v);if(s.search(/("|,|\n)/)>=0)return'"'+s.replace(/"/g,'""')+'"';return s}
function td(v,cls){return'<td class="'+(cls||'dim')+'">'+esc(v||'—')+'</td>'}
function tn(v,cls){var n=parseInt(v);return'<td class="num '+(cls||'')+'">'+(isNaN(n)||v===''||v===null||v===undefined?'<span style="color:#ccc">—</span>':fmt(n))+'</td>'}
function tl(url,label,cls){if(!url)return'<td class="dim">—</td>';return'<td class="lc '+(cls||'')+'"><a href="'+esc(url)+'" target="_blank">'+esc(label||url)+'</a></td>'}

function getCreatorFields(c){
  const isIG = c.platform === 'instagram';
  return {
    isIG,
    name:    isIG ? (c.full_name||c.username||'') : (c.channel_name||''),
    handle:  isIG ? ('@'+(c.username||'')) : (c.handle||''),
    url:     isIG ? (c.profile_url||'') : (c.handle_url||c.channel_url||''),
    subs:    isIG ? (c.followers||0) : (c.subscribers||0),
    thumb:   c.thumbnail||'',
    quality: isIG ? Math.round(c.local_match_score||0) : (c._quality_score||0),
    gender:  isIG ? _igGender(c) : (c._gender_label||'unknown'),
    country: c.country||'',
    views:   isIG ? '' : (c.total_views||0),
    vids:    isIG ? (c.posts_count||'') : (c.video_count||''),
    created: isIG ? '' : (c.channel_created||''),
    niche:   isIG ? (c.source_hashtag||c.genre_match||'') : (c.description||'').substring(0,30),
    email:   c.email||'',
    phone:   c.phone||'',
    ig:      isIG ? c.profile_url : (c.instagram_url||''),
    website: isIG ? (c.external_url||'') : (c.website||c.aggregator_url||''),
    vtitle:  isIG ? 'Sample post' : (c.video_title||''),
    vurl:    isIG ? (c.sample_post_url||'') : (c.video_url||''),
    vdate:   isIG ? '' : (c.video_published||''),
    vviews:  isIG ? '' : (c.video_views||''),
    vlikes:  isIG ? '' : (c.video_likes||''),
    vcmts:   isIG ? '' : (c.video_comments||''),
    match:   c.match_status||'review',
    ai:      c.ai_score,
    evidence:isIG ? (c.evidence||c.source_hashtag||'') : (c._creator_evidence||c.video_title||''),
    reason:  c.reject_reason||c.review_reason||c.ai_reason||'',
  };
}

function _igGender(c){
  const gc = c.gender_confidence||0;
  if(gc>60) return 'male';
  return 'unknown';
}

function matchCls(s){
  if(s==='high')   return 'b-match-high';
  if(s==='review'||s==='mid') return 'b-match-mid';
  return 'b-match-low';
}
function matchLabel(s){
  if(s==='high')   return 'High';
  if(s==='review'||s==='mid') return 'Mid';
  return 'Low';
}
function genderIcon(g){
  if(g==='male')   return '<span style="font-family:var(--font);font-size:9px;font-weight:800;color:#555;text-transform:uppercase">M</span>';
  if(g==='female') return '<span style="font-family:var(--font);font-size:9px;font-weight:800;color:#555;text-transform:uppercase">F</span>';
  return '<span style="font-family:var(--font);font-size:9px;font-weight:600;color:#aaa;text-transform:uppercase">—</span>';
}
function qualityCls(q){
  if(q>=70) return 'b-green';
  if(q>=45) return 'b-yellow';
  return 'b-red';
}

function renderTable(){
  const tbody = document.getElementById('tbody');
  const totN  = document.getElementById('totN');
  tbody.innerHTML='';

  const filterSel = document.getElementById('filterSel').value;
  let visible = displayOrder.filter(i=>{
    const m = ALL_CREATORS[i].match_status||'review';
    if(filterSel==='high') return m==='high';
    if(filterSel==='high_mid') return m==='high'||m==='review'||m==='mid';
    return true;
  });

  totN.textContent=visible.length;

  if(!visible.length){
    tbody.innerHTML='<tr><td colspan="23" class="empty">No creators match the current filter.</td></tr>';
    return;
  }

  visible.forEach(ci=>{
    const c = ALL_CREATORS[ci];
    const f = getCreatorFields(c);
    const tr = document.createElement('tr');
    tr.id='tr'+ci;

    const initials = avatarInitials(f.name);
    const bgColor = avatarColor(f.name || f.handle);
    const fallbackAvatar = '<span class="pfallback" style="background:'+bgColor+';display:none">'+initials+'</span>';

    const thumb = f.thumb
      ? '<img src="'+esc(f.thumb)+'" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'" alt="">'+fallbackAvatar
      : '<span class="pfallback" style="background:'+bgColor+'">'+initials+'</span>';

    const nameCell =
      '<div class="pcell">'+thumb+
      '<div><div class="pname"><a href="'+esc(f.url)+'" target="_blank">'+esc(f.name)+'</a></div>'+
      '<div class="phandle">'+esc(f.handle)+'</div></div></div>';

    const videoCell = f.vurl
      ? '<td class="vtc"><a href="'+esc(f.vurl)+'" target="_blank">'+esc((f.vtitle||'View').substring(0,40))+'</a>'+
        (f.vdate?'<div class="vdate">'+esc(f.vdate)+'</div>':'')+'</td>'
      : '<td class="dim">—</td>';

    const igHandle = f.ig ? (f.ig.replace(/\/$/, '').split('/').pop() || f.ig) : '';

    const aiCell = (f.ai!==null&&f.ai!==undefined&&f.ai!=='')
      ? '<td><span class="badge '+qualityCls(parseFloat(f.ai)*10)+'">'+f.ai+'/10</span></td>'
      : '<td class="dim">—</td>';

    tr.innerHTML =
      '<td style="text-align:center"><input type="checkbox" id="ck'+ci+'" onchange="chk('+ci+')"></td>'+
      '<td style="text-align:center" title="'+(f.isIG?'Instagram':'YouTube')+'"><span class="'+(f.isIG?'plt-ig':'plt-yt')+'">'+(f.isIG?'IG':'YT')+'</span></td>'+
      '<td>'+nameCell+'</td>'+
      '<td><span class="badge '+matchCls(f.match)+'">'+matchLabel(f.match)+'</span></td>'+
      aiCell+
      '<td><span class="badge '+qualityCls(f.quality)+'">'+f.quality+'</span></td>'+
      '<td style="text-align:center;font-size:13px">'+genderIcon(f.gender)+'</td>'+
      '<td><span class="badge b-blue">'+fmt(f.subs)+'</span></td>'+
      td(f.country||'—')+
      tn(f.views)+
      td(f.vids||'—')+
      td(f.created||'—')+
      '<td class="nc dim" title="'+esc(f.niche)+'">'+esc((f.niche||'—').substring(0,25))+'</td>'+
      (f.email?'<td class="lc"><a href="mailto:'+esc(f.email)+'">'+esc(f.email)+'</a></td>':'<td class="dim">—</td>')+
      td(f.phone||'—')+
      (f.ig&&igHandle?tl(f.ig,'@'+igHandle):'<td class="dim">—</td>')+
      (f.website?tl(f.website, f.website.replace(/^https?:\/\/(www\.)?/,'').substring(0,22)):'<td class="dim">—</td>')+
      videoCell+
      tn(f.vviews,'gv')+tn(f.vlikes,'gv')+tn(f.vcmts,'gv')+
      '<td class="nc dim" title="'+esc(f.evidence)+'">'+esc((f.evidence||'—').substring(0,35))+'</td>'+
      '<td class="nc dim" title="'+esc(f.reason)+'">'+esc((f.reason||'—').substring(0,40))+'</td>';

    tr.onclick=e=>{if(e.target.tagName!=='INPUT'&&e.target.tagName!=='A')toggle(ci)};
    tbody.appendChild(tr);
  });
  updCnt();
}

function buildDisplayOrder(){
  displayOrder=ALL_CREATORS.map((_,i)=>i);
  applySort(false);
}

function applySort(doRender=true){
  const v=document.getElementById('sortSel').value;
  displayOrder.sort((a,b)=>{
    const ca=ALL_CREATORS[a], cb=ALL_CREATORS[b];
    if(v==='ai_desc'){
      const sa=parseFloat(ca.ai_score)||0, sb=parseFloat(cb.ai_score)||0;
      return sb-sa;
    }
    if(v==='quality_desc'){
      const qa=ca.platform==='instagram'?(ca.local_match_score||0):(ca._quality_score||0);
      const qb=cb.platform==='instagram'?(cb.local_match_score||0):(cb._quality_score||0);
      return qb-qa;
    }
    if(v==='subs_desc'){
      const sa=parseInt(ca.platform==='instagram'?ca.followers:ca.subscribers)||0;
      const sb=parseInt(cb.platform==='instagram'?cb.followers:cb.subscribers)||0;
      return sb-sa;
    }
    if(v==='subs_asc'){
      const sa=parseInt(ca.platform==='instagram'?ca.followers:ca.subscribers)||0;
      const sb=parseInt(cb.platform==='instagram'?cb.followers:cb.subscribers)||0;
      return sa-sb;
    }
    if(v==='match'){
      const order={high:0,review:1,mid:1,rejected:2,low:2};
      return (order[ca.match_status]||1)-(order[cb.match_status]||1);
    }
    return 0;
  });
  if(doRender) renderTable();
}

function toggle(i){const ck=document.getElementById('ck'+i);if(ck){ck.checked=!ck.checked;chk(i);}}
function chk(i){
  const ck=document.getElementById('ck'+i),tr=document.getElementById('tr'+i);
  if(ck&&tr){ck.checked?(selected.add(i),tr.classList.add('sel')):(selected.delete(i),tr.classList.remove('sel'));}
  updCnt();
}
function toggleAll(el){
  displayOrder.forEach(i=>{
    const ck=document.getElementById('ck'+i),tr=document.getElementById('tr'+i);
    if(ck&&tr){ck.checked=el.checked;el.checked?(selected.add(i),tr.classList.add('sel')):(selected.delete(i),tr.classList.remove('sel'));}
  });
  updCnt();
}
function updCnt(){
  document.getElementById('selN').textContent=selected.size;
  document.getElementById('csvBtn').disabled=ALL_CREATORS.length===0;
}

function downloadCSV(){
  const idxs=selected.size>0?Array.from(selected):displayOrder;
  const rows=idxs.map(i=>ALL_CREATORS[i]);
  const headers=['Platform','Name','Handle','URL','Followers','Country','Total Views','Videos',
    'Created','Niche','Email','Phone','Instagram','Website','Latest Content URL',
    'Latest Content Title','Publish Date','Vid Views','Vid Likes','Vid Comments',
    'Match Status','AI Score','Quality Score','Evidence','Reason'];
  const lines=[headers.map(ce).join(',')];
  rows.forEach(c=>{
    const f=getCreatorFields(c);
    lines.push([
      f.isIG?'Instagram':'YouTube',f.name,f.handle,f.url,f.subs,f.country,
      f.views,f.vids,f.created,f.niche,f.email,f.phone,f.ig,f.website,
      f.vurl,f.vtitle,f.vdate,f.vviews,f.vlikes,f.vcmts,
      c.match_status||'',c.ai_score||'',f.quality,f.evidence,f.reason
    ].map(ce).join(','));
  });
  const blob=new Blob(['\uFEFF'+lines.join('\n')],{type:'text/csv;charset=utf-8;'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='creators_'+new Date().toISOString().substring(0,10)+'.csv';
  a.click();
}

// Init
buildDisplayOrder();
renderTable();
</script>
</body>
</html>
""".strip()


def render_creator_table(creators: list[dict], height: int = 700) -> None:
    """Render creators in a GAS-style rich HTML table with thumbnails, links, all fields."""
    if not creators:
        return
    data_json = json.dumps(creators, default=str)
    html = _TABLE_TEMPLATE.replace("__DATA__", data_json)
    components.html(html, height=height, scrolling=True)