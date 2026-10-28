[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$environmentFolder = Join-Path $PSScriptRoot '.venv'
$environmentPython = Join-Path $environmentFolder 'Scripts\python.exe'
if ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($PSScriptRoot)).AvailableFreeSpace -lt 8GB) {
    throw 'Free at least 8 GiB on the project drive first.'
}
$modelRoot = if ($env:KINETIC_LYRICS_MODEL_CACHE) { $env:KINETIC_LYRICS_MODEL_CACHE } elseif ($env:OLLAMA_MODELS) { $env:OLLAMA_MODELS } else { Join-Path $HOME '.ollama\models' }
$env:HF_HOME = Join-Path $modelRoot 'huggingface'
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME 'hub'
$env:HUGGINGFACE_HUB_CACHE = $env:HF_HUB_CACHE
$env:U2NET_HOME = Join-Path $modelRoot 'background-removal'
$env:PIP_CACHE_DIR = Join-Path $modelRoot 'pip-cache'
if (-not (Test-Path -LiteralPath $environmentPython)) {
    & py -3.12 -m venv $environmentFolder
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the dedicated Python 3.12 environment.' }
}
& $environmentPython -m pip install 'torch==2.11.0+cu130' 'torchaudio==2.11.0+cu130' 'torchvision==0.26.0+cu130' --index-url https://download.pytorch.org/whl/cu130
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed.' }
& $environmentPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Lyric-video dependency installation failed.' }
& $environmentPython -c "import torch; from diffusers import Flux2Pipeline; from rembg import new_session; print('CUDA available:', torch.cuda.is_available()); assert torch.cuda.is_available()"
if ($LASTEXITCODE -ne 0) { throw 'Runtime verification failed.' }
Write-Host 'Dedicated environment ready. Run kinetic-lyrics.cmd from the project root.'
