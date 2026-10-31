// Optional video step: the "Animate each image" checkbox and the image-to-video model picker.
let videoModels=[];
const VIDEO_MODES=['fullscreen','verse'];
function videoHelp(note=''){
 const model=videoModels.find(m=>m.id===$('videoModel').value);
 if(model)$('videoModelLink').href='https://huggingface.co/'+model.id;
 $('videoModelLink').hidden=!model;
 if(!videoModels.length){$('videoHelp').textContent='Restart Kinetic Lyrics to enable video models.';return}
 const off=$('videoGeneration').checked?'':'Off: images stay still. ';
 $('videoHelp').textContent=note+off+`After the artwork is approved, every image becomes a ${Math.round(model.frames/model.fps)}-second clip that plays forwards and back behind the lyrics. Works with full-screen and verse-inspired artwork. ${model.description} ${model.license}. Allow ~${model.disk_gb} GB for the first download. Run src/video_generation/setup.ps1 once before first use.`;
}
function syncVideoControls(note=''){
 $('videoGeneration').disabled=!videoModels.length;
 $('videoModel').disabled=!videoModels.length||!$('videoGeneration').checked;
 videoHelp(note);
}
function initVideo(cfg){
 videoModels=cfg.video_models||[];
 const current=$('videoModel').value;
 $('videoModel').replaceChildren(...videoModels.map(m=>new Option(m.name,m.id)));
 if(videoModels.some(m=>m.id===current))$('videoModel').value=current;
 syncVideoControls();
}
document.addEventListener('DOMContentLoaded',()=>{
 $('videoGeneration').addEventListener('change',()=>{
  // Clips replace whole-frame backdrops, so turning video on picks a layout that has them.
  if($('videoGeneration').checked&&!VIDEO_MODES.includes($('artworkMode').value)){
   $('artworkMode').value='fullscreen';
   $('artworkMode').dispatchEvent(new Event('change',{bubbles:true}));
   return syncVideoControls('Artwork layout switched to full-screen artwork. ');
  }
  syncVideoControls();
 });
 $('videoModel').addEventListener('change',()=>syncVideoControls());
 $('artworkMode').addEventListener('change',()=>{
  if($('videoGeneration').checked&&!VIDEO_MODES.includes($('artworkMode').value)){
   $('videoGeneration').checked=false;
   return syncVideoControls('Video turned off: this artwork layout has no full-frame images to animate. ');
  }
  syncVideoControls();
 });
});
window.initVideo=initVideo;
window.syncVideoControls=syncVideoControls;
