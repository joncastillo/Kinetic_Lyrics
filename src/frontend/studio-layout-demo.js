// A small moving picture under Artwork layout that shows what the chosen layout does. Greenscreen plays its three
// steps: scenery painted on green, a matching sky painted alone, then the green keyed out so the lyrics sit in the
// sky behind the hills.
(()=>{
 const HILLS='M0 92 C30 70 55 74 80 84 C105 94 120 66 150 70 C180 74 190 90 220 86 L240 84 L240 135 L0 135 Z';
 const NEAR='M0 112 C40 98 70 104 100 110 C140 118 170 98 240 106 L240 135 L0 135 Z';
 const scenery=`<path d="${HILLS}" fill="#3f5f3a"/><path d="${NEAR}" fill="#2a4229"/>
  <circle cx="60" cy="96" r="5" fill="#1d2f1c"/><rect x="58.5" y="96" width="3" height="10" fill="#1d2f1c"/>
  <circle cx="190" cy="92" r="7" fill="#1d2f1c"/><rect x="188.5" y="92" width="3" height="14" fill="#1d2f1c"/>`;
 const sky=`<defs><linearGradient id="ldSky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b2a5a"/><stop offset="1" stop-color="#e59a6a"/></linearGradient></defs>
  <rect width="240" height="135" fill="url(#ldSky)"/><circle cx="180" cy="34" r="10" fill="#fde7b0" opacity=".9"/>
  <ellipse cx="70" cy="40" rx="30" ry="6" fill="#fff" opacity=".18"/><ellipse cx="140" cy="58" rx="40" ry="5" fill="#fff" opacity=".14"/>`;
 const words=`<text x="120" y="73" text-anchor="middle" font-family="Georgia,serif" font-size="24" font-style="italic" fill="#fff8e7" stroke="#2a1d10" stroke-width=".6">wise men say</text>`;
 const frame=(inner,caption)=>`<figure class="ld-frame"><svg viewBox="0 0 240 135" role="img" aria-label="${caption}">${inner}</svg><figcaption>${caption}</figcaption></figure>`;
 const DEMOS={
  matte:{help:'Three steps for each image. The hills, trees and buildings are painted in front of a flat green sky; a matching sky is painted on its own; the green is cut out so the sky shows through. The lyrics are drawn into that sky, so the scenery always stays in front of the letters, as if the words were part of the evening.',
   frames:[frame(`<rect width="240" height="135" fill="#00d84a"/>${scenery}`,'1 · Scenery on green'),
           frame(sky,'2 · A matching sky'),
           frame(`${sky}${words}${scenery}`,'3 · Green keyed out: lyrics in the sky')]},
  cutout:{help:'Each illustration is cut out of its background and placed in a framed box on a styled backdrop, with the lyrics beside it.',
   frames:[frame(`<rect width="240" height="135" fill="#2b2140"/><circle cx="30" cy="20" r="40" fill="#3d2f5c"/><rect x="18" y="22" width="104" height="92" rx="10" fill="#f3e3c3"/><path d="M28 104 C50 70 80 74 112 104 Z" fill="#c9774b"/><circle cx="70" cy="58" r="14" fill="#7a4b8f"/><text x="134" y="58" font-family="Georgia,serif" font-size="13" fill="#fff">wise men</text><text x="134" y="78" font-family="Georgia,serif" font-size="13" fill="#ffd27a">say</text>`,'Illustration in a box, lyrics beside it')]},
  fullscreen:{help:'Each illustration fills the screen and is painted with a calm area kept free for the lyrics; scenes blend into one another.',
   frames:[frame(`${sky}${scenery}<rect x="40" y="44" width="160" height="34" rx="6" fill="#000" opacity=".18"/>${words}`,'Full-screen scene, lyrics in its calm space')]},
  verse:{help:'Like full-screen, but each background is a painted picture of what the lyrics mean, often a visual metaphor, rather than the story\'s scene.',
   frames:[frame(`<rect width="240" height="135" fill="#1e3550"/><circle cx="120" cy="80" r="44" fill="#d9a441" opacity=".85"/><path d="M120 40 C100 70 140 90 120 124" stroke="#fff" stroke-width="3" fill="none" opacity=".7"/><path d="M60 120 Q120 90 180 120" stroke="#9fd3c7" stroke-width="4" fill="none"/>${words}`,'A painted metaphor for the verse')]}};
 const css=`.layout-demo{margin:6px 0 4px}.layout-demo .ld-strip{display:flex;gap:8px;flex-wrap:wrap}
  .layout-demo .ld-frame{margin:0;flex:1 1 150px;max-width:220px}.layout-demo svg{width:100%;height:auto;display:block;border-radius:8px;border:1px solid rgba(255,255,255,.12)}
  .layout-demo figcaption{font-size:11px;opacity:.8;margin-top:3px}
  .layout-demo.playing .ld-frame{animation:ldPulse 6s infinite;opacity:.45}
  .layout-demo.playing .ld-frame:nth-child(2){animation-delay:2s}.layout-demo.playing .ld-frame:nth-child(3){animation-delay:4s}
  @keyframes ldPulse{0%,33%{opacity:1;transform:translateY(-2px)}34%,100%{opacity:.45;transform:none}}
  @media (prefers-reduced-motion:reduce){.layout-demo.playing .ld-frame{animation:none;opacity:1}}
  .layout-demo .ld-help{font-size:12px;opacity:.85;margin-top:4px}`;
 function show(){
  const select=document.getElementById('artworkMode');if(!select)return;
  let box=document.getElementById('layoutDemo');
  if(!box){
   const style=document.createElement('style');style.textContent=css;document.head.append(style);
   box=document.createElement('div');box.id='layoutDemo';box.className='layout-demo';box.setAttribute('aria-live','polite');select.after(box);
  }
  const demo=DEMOS[select.value]||DEMOS.cutout;
  box.classList.toggle('playing',demo.frames.length>1);
  box.innerHTML=`<div class="ld-strip">${demo.frames.join('')}</div><div class="ld-help">${demo.help}</div>`;
 }
 document.addEventListener('change',event=>{if(event.target?.id==='artworkMode')show()});
 // profiles and saved projects set the layout without a change event
 document.addEventListener('DOMContentLoaded',show);if(document.readyState!=='loading')show();
 setInterval(()=>{const select=document.getElementById('artworkMode'),box=document.getElementById('layoutDemo');
  if(select&&box&&box.dataset.mode!==select.value){box.dataset.mode=select.value;show()}},1000);
})();
