"""Keep finer-current clips at real-time browser playback across gallery rebuilds."""
from pathlib import Path
import re,sys
root=Path(sys.argv[1] if len(sys.argv)>1 else 'gallery')
routes=['experiments/langmuir-ak20-current2x','previews/langmuir-ak20-current2x-first10','previews/langmuir-ak20-current2x-velocity']
clips={'underwater.mp4','horizontal_velocity_5to30.mp4','horizontal_velocity_0to30.mp4','vorticity_isosurfaces_first10.mp4','vorticity_cutaway_first10.mp4','currents_first10.mp4'}
replacements={
'Full surface and current videos represent 30 physical seconds, approximately 150 seconds of playback at 0.2× speed.':'Full videos represent 30 physical seconds. Current videos now default to real-time playback (about 30 seconds); surface videos remain at 0.2× speed.',
'The complete wave-averaged current evolution at 0.2× speed.':'The complete wave-averaged current evolution at 1× simulation speed (real time). Use the playback selector below to slow it down.',
'Movies play at <strong>0.2× speed</strong>.':'Current movies play at <strong>1× simulation speed (real time)</strong>; wave movies remain at <strong>0.2× speed</strong>.',
'Both movies play at <strong>0.2× speed</strong>.':'Both current movies now play at <strong>1× simulation speed (real time)</strong>. Use the playback selectors to return to slow motion.',
}
total=0
for route in routes:
 p=root/route/'index.html'
 if not p.exists():continue
 s=p.read_text()
 def tag(m):
  global total
  block=m.group(0)
  srcs=re.findall(r'\bsrc="([^"]+)"',block)
  if not any(Path(src).name in clips for src in srcs):return block
  total+=1
  if 'data-current-playback' not in block:block=block.replace('<video','<video data-current-playback="1"',1)
  return block
 s=re.sub(r'<video\b[^>]*>.*?</video>',tag,s,flags=re.S)
 for old,new in replacements.items():s=s.replace(old,new)
 if 'data-current-playback' in s and 'src="../../assets/current-playback.js"' not in s:
  assert '</body>' in s
  s=s.replace('</body>','<script src="../../assets/current-playback.js" defer></script></body>')
 p.write_text(s)
print(f'Configured {total} current-video players for real-time playback; wave players unchanged.')
