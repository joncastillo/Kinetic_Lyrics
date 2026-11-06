import subprocess,sys,re
from pathlib import Path
from PIL import Image
C=r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ref=Path(sys.argv[1]);out=ref/'shots';out.mkdir(exist_ok=True)
for name in sys.argv[2:]:
    svg=(ref/f'{name}.svg').read_text(encoding='utf8')
    sid=re.search(r'<svg id="([^"]+)"',svg).group(1)
    m=re.search(r'"duration":(\d+)',svg); dur=int(m.group(1)) if m else 4000
    times=[round(dur*i/23) for i in range(24)]
    frames=[]
    for t in times:
        html=f'<html><body style="margin:0;background:#fff">{svg}<script>var e=document.getElementById("{sid}");function go(){{if(!e.svgatorPlayer){{return setTimeout(go,20)}};var p=e.svgatorPlayer;p.ready(function(q){{q.pause();q.seekTo({t});}})}};go();</script></body></html>'
        h=out/f'{name}_{t}.html';h.write_text(html,encoding='utf8')
        p=out/f'{name}_{t:05d}.png'
        subprocess.run([C,'--headless=new','--disable-gpu','--hide-scrollbars','--window-size=700,400','--virtual-time-budget=1500',f'--screenshot={p}',h.as_uri()],capture_output=True,timeout=60)
        if p.exists():frames.append(Image.open(p).convert('RGB').resize((280,160)))
    sheet=Image.new('RGB',(280*6,160*4),'white')
    for i,f in enumerate(frames):sheet.paste(f,((i%6)*280,(i//6)*160))
    sheet.save(ref/f'{name}_sheet.png');print(name,dur,len(frames))
