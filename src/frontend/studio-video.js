// Optional video step: the "Animate each image" checkbox and the image-to-video model picker.
let videoModels=[];
const VIDEO_MODES=['fullscreen','verse'];
function videoHelp(){
 const model=videoModels.find(m=>m.id===$('videoModel').value);
 const mode=$('artworkMode').value;
 if(!VIDEO_MODES.includes(mode)){$('videoHelp').textContent='Video generation needs full-screen or verse-inspired artwork. Change the artwork layout to use it.';return}
 $('videoHelp').textContent=model?`After the artwork is approved, every image becomes a ${Math.round(model.frames/model.fps)}-second clip that plays forwards and back behind the lyrics. ${model.description} ${model.license}. Allow ~${model.disk_gb} GB for the first download. Run src/video_generation/setup.ps1 once before first use.`:'Restart Kinetic Lyrics to enable video models.';
}
function syncVideoControls(){
 const allowed=VIDEO_MODES.includes($('artworkMode').value)&&videoModels.length>0;
 $('videoGeneration').disabled=!allowed;
 if(!allowed)$('videoGeneration').checked=false;
 $('videoModel').disabled=!allowed||!$('videoGeneration').checked;
 videoHelp();
}
function initVideo(cfg){
 videoModels=cfg.video_models||[];
 const current=$('videoModel').value;
 $('videoModel').replaceChildren(...videoModels.map(m=>new Option(m.name,m.id)));
 if(videoModels.some(m=>m.id===current))$('videoModel').value=current;
 syncVideoControls();
}
document.addEventListener('DOMContentLoaded',()=>{
 for(const id of ['videoGeneration','videoModel','artworkMode'])$(id).addEventListener('change',syncVideoControls);
});
window.syncVideoControls=syncVideoControls;
