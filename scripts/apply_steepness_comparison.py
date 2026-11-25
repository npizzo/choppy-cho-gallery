"""Reapply a verified 0–10 s paired movie section after frozen publishers rebuild pages."""
from pathlib import Path
import json,hashlib,re,sys,html
SLUG='ak10-ak20-first10'
ROUTES=('experiments/langmuir-ak10-current2x','experiments/langmuir-ak20-current2x','previews/langmuir-ak20-current2x-first10')
START='<!-- steepness-first10:start -->';END='<!-- steepness-first10:end -->'
def require(condition,message):
    if not condition:raise ValueError(message)
def apply(root):
    root=Path(root);base=root/'supplements'/SLUG
    if not (base/'manifest.json').exists():return 0
    record=json.loads((base/'manifest.json').read_text());ready=record['status']=='complete'
    require(record['status'] in ('processing','complete'),'Unknown comparison state')
    require(set(record['clips'])==({'ak10','ak20'} if ready else {'ak20'}),'Incomplete clip pair')
    for case,entry in record['clips'].items():
        for ext in ('mp4','png','json','verified.json'):
            name=entry['assets'][ext];require(name==case+'_parent_plus_cho_first10.'+ext,'Unexpected asset path')
            p=base/name;require(p.is_file() and not p.is_symlink(),'Missing comparison asset')
            require(hashlib.sha256(p.read_bytes()).hexdigest()==entry['sha256'][ext],'Comparison hash changed')
        meta=json.loads((base/entry['assets']['json']).read_text());check=json.loads((base/entry['assets']['verified.json']).read_text())
        require(meta['physical_interval_s']==[0.,10.] and meta['physical_playback_speed']==.2,'Wrong comparison timing')
        require(meta['cho_enabled'] and meta['damping_multiplier']==2.4 and meta['vertical_exaggeration']==1,'Wrong comparison physics')
        require(meta['render_complete'] and check['verified'] and check['all_frames_decoded'],'Unverified movie')
        require(check['sha256']==entry['sha256']['mp4'],'Decode check does not match movie')
    if ready:
        camera=[json.loads((base/e['assets']['json']).read_text())['camera_zmax_m'] for e in record['clips'].values()]
        require(abs(camera[0]-camera[1])<1e-12,'Unmatched camera scales')
    prefix='../../supplements/'+SLUG+'/'
    columns=[]
    for case,title in [('ak10','ak = 0.1'),('ak20','ak = 0.2')]:
        if case in record['clips']:
            entry=record['clips'][case]
            body=f'<video data-steepness-case="{case}" controls playsinline preload="metadata" poster="{prefix}{entry["assets"]["png"]}"><source src="{prefix}{entry["assets"]["mp4"]}" type="video/mp4"></video><p><a href="{prefix}{entry["assets"]["json"]}">Movie metadata</a></p>'
        else:body='<div style="padding:45px 20px;background:#eef4f6;border-radius:8px">Cho is being computed from the saved 0–10 s parent/current history. This video will appear automatically after rendering and verification.</div>'
        columns.append(f'<div><h3>{title}</h3>{body}</div>')
    controls='<p><button type="button" data-pair-play>Play both</button> <button type="button" data-pair-pause>Pause both</button> <button type="button" data-pair-reset>Back to t = 0</button> <span data-pair-time>t = 0.00 s</span></p>' if ready else ''
    note='Matched camera, lighting, and physical height scale.' if ready else 'The ak = 0.2 movie is available; the ak = 0.1 comparison is processing.'
    block=f'''{START}
<section id="steepness-first10" data-paired-surfaces>
<style>#steepness-first10 .steepness-pair{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}}#steepness-first10 video{{width:100%;height:auto}}#steepness-first10 button{{padding:8px 12px;cursor:pointer}}@media(max-width:760px){{#steepness-first10 .steepness-pair{{grid-template-columns:1fr}}}}</style>
<h2>First 10 seconds: parent + Cho</h2>
<p>Both cases use 2.4× Cho damping and play at 0.2× speed: 10 physical seconds in about 50 seconds of video. {note} Wave heights and roughness are not magnified.</p>
{controls}<div class="steepness-pair">{''.join(columns)}</div>
<p style="font-size:14px">Initially monochromatic 8 cm waves, the same domain, current seed, wind forcing, grids and retained parent modes. These are finite-mode simulations; late-time details require convergence checks. Slower playback does not recover motion between the saved 0.01 s snapshots.</p>
</section><script src="{prefix}comparison.js" defer></script>
{END}'''
    count=0
    for route in ROUTES:
        p=root/route/'index.html'
        if not p.exists():continue
        content=p.read_text();require(content.count(START)==content.count(END)<=1,'Broken comparison markers')
        content=re.sub(re.escape(START)+'.*?'+re.escape(END)+'\n?','',content,flags=re.S)
        index=content.find('<!-- surface-tracer:start -->')
        if index<0:index=content.find('<section')
        if index<0:index=content.find('<footer')
        require(index>=0,'Missing comparison insertion anchor')
        p.write_text(content[:index]+block+'\n'+content[index:]);count+=1
    return count
if __name__=='__main__':print('Applied steepness comparison to',apply(sys.argv[1] if len(sys.argv)>1 else 'gallery'),'pages')
