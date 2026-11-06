// Compatibility with profiles created by other editions. Illustrations remain still.
let videoModels=[];
function syncVideoControls(){const box=document.getElementById('videoGeneration');if(box)box.checked=false;}
function syncPictureKinds(){syncVideoControls();}
function showPictureKinds(){syncVideoControls();}
function syncEndFrameModels(){}
window.initVideo=()=>syncVideoControls();
