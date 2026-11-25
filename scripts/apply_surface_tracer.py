"""Keep the four-panel surface/tracer movie on both experiment landing pages."""
from pathlib import Path
import hashlib,json,re,sys
SLUG='surface-tracer-comparison'
ROUTES=('experiments/langmuir-ak10-current2x','experiments/langmuir-ak20-current2x','previews/langmuir-ak20-current2x-first10')
START='<!-- surface-tracer:start -->';END='<!-- surface-tracer:end -->'
def apply(root):
 root=Path(root);base=root/'supplements'/SLUG;p=base/'manifest.json'
 if not p.exists():return 0
 r=json.loads(p.read_text());assert r['complete'] is True
 for name,digest in r['sha256'].items():
  assert name in ('surfaces_and_tracers.mp4','surfaces_and_tracers.png','surfaces_and_tracers.json','surfaces_and_tracers.verified.json','tracer_validation.json')
  f=base/name;assert f.is_file() and not f.is_symlink();assert hashlib.sha256(f.read_bytes()).hexdigest()==digest
 m=json.loads((base/'surfaces_and_tracers.json').read_text());v=json.loads((base/'surfaces_and_tracers.verified.json').read_text())
 assert m['render_complete'] and v['verified'] and v['all_frames_decoded']
 assert m['physical_interval_s']==[0.,30.] and m['physical_playback_speed']==.2 and m['cho_damping_multiplier']==2.4
 assert v['sha256']==r['sha256']['surfaces_and_tracers.mp4']
 assert m['tracer']['colors_clipped'] is False and all(x<1e-9 for x in m['tracer']['mass_relative_errors'].values())
 prefix='../../supplements/'+SLUG+'/'
 block=f'''{START}
<section id="surface-tracer-comparison">
<h2>Waves and tracer transport · ak = 0.1 versus 0.2</h2>
<p>Four synchronized panels over 0–30 s: parent + Cho surfaces above, surface-released dye below. ak = 0.1 is on the left; ak = 0.2 is on the right. Both use 2.4× Cho damping and play at 0.2× speed.</p>
<video style="max-height:none" controls playsinline preload="metadata" poster="{prefix}surfaces_and_tracers.png"><source src="{prefix}surfaces_and_tracers.mp4" type="video/mp4"></video>
<p>The dye panels share a fixed, labeled concentration scale throughout. The nonlinear color mapping reveals dilute dye while retaining the concentrated surface release; there is no frame-by-frame rescaling or concentration clipping. Depth is enlarged 2× for visibility.</p>
<details><summary>Tracer method and interpretation</summary><p>Following <a href="https://doi.org/10.1017/jfm.2023.920">Wagner et al. (2023), equation 3.13 and figure 7</a>, the dye starts in the surface cell and is transported by the Lagrangian-mean current with diffusivity 10⁻⁷ m²/s. Identical initial concentration and surface inventory are used in both cases.</p><p>This is an offline passive-tracer calculation using the saved three-dimensional currents, linearly interpolated between their 0.1 s snapshots. It does not alter the waves or currents, and Cho does not feed back into the current. The saved-current cadence and the transport scheme’s spatial numerical diffusion limit small-scale interpretation. Tracer displays hold each saved 0.1 s state; surface movies retain their 0.01 s cadence. The clock is elapsed simulation time, starting from the pre-aged wind-drift state.</p><p>Checks cover tracer mass conservation, nonnegative concentration, periodic transport refinement, and a short half-timestep comparison. These are numerical consistency checks, not proof of convergence of the full turbulent mixing calculation.</p></details>
<p><a href="{prefix}surfaces_and_tracers.mp4">Download the four-panel movie</a> · <a href="{prefix}surfaces_and_tracers.json">Rendering details</a> · <a href="{prefix}tracer_validation.json">Tracer checks</a></p>
</section>
{END}'''
 count=0
 for route in ROUTES:
  p=root/route/'index.html'
  if not p.exists():continue
  s=p.read_text();assert s.count(START)==s.count(END)<=1
  s=re.sub(re.escape(START)+'.*?'+re.escape(END)+'\n?','',s,flags=re.S)
  # Insert before an existing comparison marker, never inside its replacement block.
  anchor='<!-- steepness-first10:start -->'
  i=s.find(anchor)
  if i<0:i=s.find('<section')
  assert i>=0
  p.write_text(s[:i]+block+'\n'+s[i:]);count+=1
 return count
if __name__=='__main__':print('Applied surface/tracer video to',apply(sys.argv[1] if len(sys.argv)>1 else 'gallery'),'pages')
