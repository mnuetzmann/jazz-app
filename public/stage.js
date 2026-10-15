// The screen: rotates your pictures behind the music, finds the calmest corner of each one
// for the "now playing" caption, and shows each song's album cover (a small tile, plus a
// big "now playing" moment when the song starts).
const stage = (() => {
  const IMAGE_SECONDS = 25;   // how long each background picture stays
  const CAPTION_SECONDS = 10; // how long the caption stays after a song starts
  const FEATURE_SECONDS = 6;  // the big cover at the start of each song; 0 turns it off
  const AWAKE_SECONDS = 5;    // how long controls stay after you touch something

  const $ = (id) => document.getElementById(id);
  const stageEl = $('stage');
  const layers = [$('slideA'), $('slideB')];
  const hud = $('hud'), art = $('art');
  const featureEl = $('feature'), featureBg = $('featureBg'), featureArt = $('featureArt');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  let library = { all: [], byStyle: {} };
  let category = null;
  let covers = [];      // cover pictures of the current style's songs (the fallback background)
  let order = [];
  let showing = null;   // url on screen
  let poolKey = null;
  let top = 0;
  let rotateTimer = null, captionTimer = null, awakeTimer = null;
  let featureTimer = null, finishTimer = null, featureAnim = null, currentCover = '';

  const shuffle = (a) => a.map((v) => [Math.random(), v]).sort((x, y) => x[0] - y[0]).map((p) => p[1]);
  const plain = (urls) => urls.map((url) => ({ url, soft: false }));

  // What to show behind the music, best first: pictures for this style, your general
  // pictures, then this style's own covers (blurred, so a small cover never looks coarse).
  function pool() {
    const own = library.byStyle[category] || library.byStyle[String(category).split('/').pop()]; // images/<style>/ matches by the style's folder name
    if (own && own.length) return plain(own);
    if (library.all.length) return plain(library.all);
    if (covers.length) return covers.map((url) => ({ url, soft: true }));
    return plain(Object.values(library.byStyle).flat());
  }

  function nextItem() {
    if (!order.length) order = shuffle(pool());
    // avoid showing the same picture twice in a row when there is a choice
    if (order.length > 1 && order[order.length - 1].url === showing) order.unshift(order.pop());
    return order.pop();
  }

  // Resolves when the picture has loaded. Decoding is a nicety that can stall in a hidden
  // tab, so it never holds things up for more than a moment; a failed or very slow load rejects.
  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const giveUp = setTimeout(() => reject(new Error('slow')), 15000);
      img.onload = () => {
        clearTimeout(giveUp);
        if (!img.decode) return resolve(img);
        Promise.race([img.decode().catch(() => {}), new Promise((r) => setTimeout(r, 1200))]).then(() => resolve(img));
      };
      img.onerror = () => { clearTimeout(giveUp); reject(new Error('load')); };
      img.src = url;
    });
  }

  // Score each corner by how much is going on there (less is better for text).
  function calmestCorner(img) {
    try {
      const W = 48, H = 27, w = 16, h = 9;
      const c = document.createElement('canvas');
      c.width = W; c.height = H;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, W, H);
      const px = ctx.getImageData(0, 0, W, H).data;
      const score = (x0, y0) => {
        let sum = 0, sumSq = 0, n = 0;
        for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) {
          const i = (y * W + x) * 4;
          const l = 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2];
          sum += l; sumSq += l * l; n++;
        }
        const mean = sum / n;
        return Math.sqrt(Math.max(sumSq / n - mean * mean, 0)) + 0.15 * mean; // busyness + brightness
      };
      const corners = {
        'pos-bl': score(0, H - h), 'pos-br': score(W - w, H - h),
        'pos-tl': score(0, 0) * 1.2, 'pos-tr': score(W - w, 0) * 1.2, // slight preference for the bottom
      };
      return Object.keys(corners).sort((a, b) => corners[a] - corners[b])[0];
    } catch {
      return 'pos-bl'; // e.g. a picture the canvas will not read
    }
  }

  // Move the caption to another corner without a jump: if it is showing, it fades out, moves while
  // invisible, then fades back in. (If it is hidden anyway, it just moves.)
  function placeCaption(corner) {
    if (hud.classList.contains(corner) && !hud.classList.contains('relocating')) return;
    const apply = () => { hud.className = corner; document.body.dataset.hudSide = corner.startsWith('pos-b') ? 'bottom' : 'top'; };
    clearTimeout(placeCaption.timer);
    if (Number(getComputedStyle(hud).opacity) < 0.05) return apply();
    hud.classList.add('relocating');
    placeCaption.timer = setTimeout(apply, 600); // apply() replaces the classes, which also ends "relocating"
  }

  async function advance(attempts = 0) {
    clearTimeout(rotateTimer);
    const item = nextItem();
    if (!item) { stageEl.classList.add('fallback'); return; }
    stageEl.classList.remove('fallback');
    try {
      const img = await loadImage(item.url);
      const next = layers[1 - top], prev = layers[top];
      next.style.backgroundImage = `url("${item.url}")`;
      next.classList.toggle('soft', item.soft);
      next.style.setProperty('--dx', `${(Math.random() * 3 - 1.5).toFixed(2)}%`);
      next.style.setProperty('--dy', `${(Math.random() * 3 - 1.5).toFixed(2)}%`);
      next.style.setProperty('--seconds', `${IMAGE_SECONDS + 8}s`);
      clearTimeout(next.settle);
      next.classList.remove('on', 'live'); void next.offsetWidth; // start its slow drift from the beginning
      next.classList.add('live', 'on');                           // fades in, and starts drifting
      prev.classList.remove('on');                                // fades out, but keeps drifting: no snap back
      clearTimeout(prev.settle);
      prev.settle = setTimeout(() => prev.classList.remove('live'), 3500); // once it is fully faded
      top = 1 - top;
      showing = item.url;
      placeCaption(calmestCorner(img));
    } catch {
      if (attempts < 5) return advance(attempts + 1); // skip an unreadable picture
    }
    rotateTimer = setTimeout(advance, IMAGE_SECONDS * 1000);
  }

  async function init() {
    try { library = await fetch('/api/images').then((r) => r.json()); } catch { /* no pictures: gradient */ }
    // Pictures usually carry the station name themselves, so the start screen then stays out of the way.
    document.body.classList.toggle('has-pictures', library.all.length + Object.keys(library.byStyle).length > 0);
    poolKey = pool().map((x) => x.url).join('|');
    advance();
  }

  // The music style changed: switch pictures if this style should look different.
  function setCategory(id, coverUrls = []) {
    category = id;
    covers = [...new Set(coverUrls.filter(Boolean))];
    const key = pool().map((x) => x.url).join('|');
    if (key === poolKey) return;
    poolKey = key;
    order = [];
    advance();
  }

  // ---- caption and album cover ----------------------------------------------------
  function holdCaption(seconds) {
    document.body.classList.add('hud-on');
    clearTimeout(captionTimer);
    captionTimer = setTimeout(() => document.body.classList.remove('hud-on'), seconds * 1000);
  }

  function resetFeature() {
    clearTimeout(featureTimer);
    clearTimeout(finishTimer);
    if (featureAnim) { featureAnim.cancel(); featureAnim = null; }
    featureEl.classList.remove('on', 'leaving');
    art.classList.remove('art-hidden');
  }

  // A new song: show its cover as a tile beside the caption.
  function songStarted(track) {
    resetFeature();
    currentCover = (track && track.cover) || '';
    if (currentCover) { art.src = currentCover; art.hidden = false; } else { art.hidden = true; art.removeAttribute('src'); }
    holdCaption(CAPTION_SECONDS);
  }

  // The music stopped (a prompt, an error): clear the cover.
  function songEnded() {
    resetFeature();
    currentCover = '';
    art.hidden = true;
    document.body.classList.remove('hud-on');
  }

  // The song's audio has begun: the cover fills the screen for a moment, then settles into its tile.
  function feature() {
    if (!FEATURE_SECONDS || !currentCover || art.hidden) return;
    resetFeature();
    featureBg.style.backgroundImage = `url("${currentCover}")`;
    featureArt.src = currentCover;
    art.classList.add('art-hidden');
    void featureEl.offsetWidth;
    featureEl.classList.add('on');
    holdCaption(FEATURE_SECONDS + CAPTION_SECONDS);
    featureTimer = setTimeout(endFeature, FEATURE_SECONDS * 1000);
  }

  function endFeature() {
    const from = featureArt.getBoundingClientRect(), to = art.getBoundingClientRect();
    featureEl.classList.add('leaving');
    const finish = () => {
      art.classList.remove('art-hidden');
      featureEl.classList.remove('on'); // fades out over the tile, which is now in the same place
      finishTimer = setTimeout(() => {
        featureEl.classList.remove('leaving');
        if (featureAnim) { featureAnim.cancel(); featureAnim = null; }
      }, 1000);
    };
    if (reduceMotion || !to.width || !from.width) return finish();
    const dx = to.left + to.width / 2 - (from.left + from.width / 2);
    const dy = to.top + to.height / 2 - (from.top + from.height / 2);
    featureAnim = featureArt.animate(
      [{ transform: 'translate(0, 0) scale(1)' }, { transform: `translate(${dx}px, ${dy}px) scale(${to.width / from.width})` }],
      { duration: 1300, easing: 'cubic-bezier(.2, .7, .2, 1)', fill: 'forwards' },
    );
    featureAnim.onfinish = finish;
  }

  function wake() {
    document.body.classList.add('awake');
    clearTimeout(awakeTimer);
    awakeTimer = setTimeout(() => {
      document.body.classList.remove('awake');
      document.dispatchEvent(new Event('controlsfaded')); // so anything else that is open can fade away with them
    }, AWAKE_SECONDS * 1000);
  }

  for (const ev of ['mousemove', 'mousedown', 'touchstart', 'keydown']) window.addEventListener(ev, wake, { passive: true });
  init();
  return { setCategory, songStarted, songEnded, feature, wake, placeCaption, next: () => advance() };
})();
