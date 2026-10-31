'use strict';
const $ = id => document.getElementById(id);
const safeFile = name => typeof name === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(name);
const finite = n => typeof n === 'number' && Number.isFinite(n);
const fmt = n => finite(n) ? new Intl.NumberFormat('en-US', {maximumSignificantDigits: 4}).format(n) : '—';
function element(tag, text, className) { const e=document.createElement(tag); if (text !== undefined) e.textContent=text; if(className)e.className=className; return e; }
function badge(state) { const values=['pending','running','partial','complete','failed','validity_limit'];const s=values.includes(state)?state:'pending';return element('span',s.replaceAll('_',' '),'badge '+s); }
function uniqueCoefficient(cases, key) { const vals=[...new Set(cases.map(c=>c.config?.[key]).filter(finite))].filter(x=>x>0); return vals.length===1?fmt(vals[0]):vals.length>1?'Varied':'—'; }
function render(s) {
  if(s.schema_version!==1 || !Array.isArray(s.cases)) throw new Error('The published snapshot has an unsupported format.');
  const version=encodeURIComponent(s.updated_at_utc||'');
  const assetUrl=name=>'assets/'+name+(version?'?v='+version:'');
  const complete=s.cases.filter(c=>c.complete===true).length;
  const state=s.state || (complete===s.cases.length&&complete?'complete':'pending');
  const b=badge(state);b.id='status';$('status').replaceWith(b);
  $('completed').textContent=complete+' / '+s.cases.length;
  $('input-coefficient').textContent=uniqueCoefficient(s.cases,'wind_growth_coefficient');
  $('loss-coefficient').textContent=uniqueCoefficient(s.cases,'parent_loss_coefficient');
  $('status-description').textContent=s.description || 'Matched wave and dye calculations are being prepared.';
  const date=new Date(s.updated_at_utc);
  $('updated').textContent=Number.isFinite(date.getTime())?'Published '+date.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})+' · '+Intl.DateTimeFormat().resolvedOptions().timeZone:'Snapshot timestamp unavailable';
  const tbody=$('case-table');tbody.replaceChildren();
  for(const c of s.cases){const row=element('tr');row.append(element('th',c.label||c.case));row.firstChild.scope='row';row.append(element('td',c.wave_treatment||c.wave_mode||'Configured'));
    row.append(element('td',finite(c.wavelength_m)?fmt(100*c.wavelength_m)+' cm':'—'));
    row.append(element('td',finite(c.actual_final_time_s)&&c.status==='validity_limit'?fmt(c.actual_final_time_s)+' / '+fmt(c.duration_s)+' s':finite(c.duration_s)?fmt(c.duration_s)+' s':'—'));
    const stage=element('td');stage.append(badge(c.status));if(c.stage)stage.append(element('div',c.stage.replaceAll('_',' '),'small muted'));row.append(stage);tbody.append(row);}
  const figures=$('figures');figures.replaceChildren();
  for(const f of (s.figures||[])){if(!safeFile(f.file))continue;const card=element('figure',undefined,'figure');const a=element('a');a.href=assetUrl(f.file);const img=element('img');img.src=a.href;img.alt=f.alt||f.title||'Computed diagnostic';img.loading='lazy';a.append(img);card.append(a);const caption=element('figcaption');caption.append(element('h3',f.title));caption.append(element('p',f.description));card.append(caption);figures.append(card);}
  $('empty').hidden=figures.childElementCount>0;
  $('result-status').textContent=figures.childElementCount?figures.childElementCount+' computed figures · preliminary':'No derived results published yet';
  const findings=$('findings');findings.replaceChildren();for(const f of s.findings||[])findings.append(element('p',f));findings.hidden=!findings.childElementCount;
  const downloads=$('downloads');downloads.replaceChildren();const snapshot=element('a','Published snapshot (JSON)');snapshot.href='snapshot.json'+(version?'?v='+version:'');downloads.append(snapshot);
  for(const d of s.downloads||[]){if(!safeFile(d.file))continue;const a=element('a',d.label);a.href=assetUrl(d.file);downloads.append(a);}
  const caveats=$('caveats');caveats.replaceChildren();for(const c of s.caveats||[])caveats.append(element('li',c));
}
let loading=false;
async function load(){if(loading)return;loading=true;const button=$('refresh');button.disabled=true;$('error').hidden=true;try{const r=await fetch('snapshot.json?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error('The published snapshot is unavailable (HTTP '+r.status+').');render(await r.json());}catch(e){$('error').textContent=e.message+' The last visible results, if any, are unchanged.';$('error').hidden=false;}finally{button.disabled=false;loading=false;}}
$('refresh').addEventListener('click',load);load();
setInterval(()=>{if(!document.hidden)load();},60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
