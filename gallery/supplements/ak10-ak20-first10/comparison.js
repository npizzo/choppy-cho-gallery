(() => {
 for (const panel of document.querySelectorAll('[data-paired-surfaces]')) {
  const clips=Array.from(panel.querySelectorAll('video[data-steepness-case]'));
  if (clips.length!==2 || panel.dataset.bound) continue;
  panel.dataset.bound='true';
  const [first,second]=clips;
  const pause=()=>clips.forEach(v=>v.pause());
  panel.querySelector('[data-pair-play]').addEventListener('click',()=>{
   second.currentTime=first.currentTime;
   clips.forEach(v=>{v.playbackRate=1;v.play().catch(()=>pause());});
  });
  panel.querySelector('[data-pair-pause]').addEventListener('click',pause);
  panel.querySelector('[data-pair-reset]').addEventListener('click',()=>{pause();clips.forEach(v=>v.currentTime=0);});
  first.addEventListener('timeupdate',()=>{
   panel.querySelector('[data-pair-time]').textContent=`t = ${Math.min(10,first.currentTime*.2).toFixed(2)} s`;
   if (!first.paused && !second.paused && Math.abs(first.currentTime-second.currentTime)>.12) second.currentTime=first.currentTime;
  });
  clips.forEach(v=>v.addEventListener('ended',pause));
 }
})();
