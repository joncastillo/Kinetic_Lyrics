"""CUDA GPU detection and per-model VRAM budgets."""
import csv
import io
import subprocess


GIB = 2**30


def detect_gpus():
    """Read capacity only; never load or evict a model here."""
    try:
        result=subprocess.run(['nvidia-smi','--query-gpu=index,name,uuid,memory.total,memory.free',
                               '--format=csv,noheader,nounits'],capture_output=True,text=True,check=True,timeout=8,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return [dict(index=int(row[0]),name=row[1].strip(),uuid=row[2].strip(),
                     total_bytes=int(float(row[3])*2**20),free_bytes=int(float(row[4])*2**20))
                for row in csv.reader(io.StringIO(result.stdout)) if len(row)==5]
    except (OSError,ValueError,subprocess.SubprocessError):
        return []

