// The encoded clips contain 0.2 simulation seconds per video second.
// Set browser playback to 5x for real-time simulation playback; keep files intact.
(() => {
  for (const video of document.querySelectorAll('video[data-current-playback]')) {
    if (video.dataset.currentPlaybackReady) continue;
    video.dataset.currentPlaybackReady = 'true';
    const label = document.createElement('label');
    label.style.cssText = 'display:block;margin:10px 0 16px;font-size:15px;';
    label.append('Current playback: ');
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Current video simulation playback speed');
    for (const [value, text] of [['1', '1× — real time'], ['0.5', '0.5× — half speed'], ['0.2', '0.2× — original slow motion']]) {
      select.add(new Option(text, value));
    }
    select.value = '1';
    const apply = () => {
      const rate = Number(select.value) / 0.2;
      video.defaultPlaybackRate = rate;
      video.playbackRate = rate;
    };
    select.addEventListener('change', apply);
    video.addEventListener('loadedmetadata', apply);
    video.addEventListener('ratechange', () => {
      const speed = video.playbackRate * 0.2;
      if ([1, 0.5, 0.2].some(v => Math.abs(v - speed) < 1e-6)) select.value = String(Number(speed.toFixed(2)));
      else select.selectedIndex = -1;
    });
    label.append(select);
    video.insertAdjacentElement('afterend', label);
    apply();
  }
})();
