"""Read only transport counters/timings from localhost. No audio or transcripts."""
import argparse
import json
from pathlib import Path
import time
from urllib.request import urlopen


def watch(seconds, port, report):
    started=time.monotonic();samples=[]
    try:
        while True:
            with urlopen(f'http://localhost:{port}/api/audio-diagnostics',timeout=3) as response:
                value=json.load(response)
            sample=dict(elapsedSeconds=round(time.monotonic()-started,1),**value)
            samples.append(sample);print(json.dumps(sample,ensure_ascii=False),flush=True)
            if time.monotonic()-started>=seconds:break
            time.sleep(min(5,max(0,seconds-(time.monotonic()-started))))
    finally:
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(samples,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,choices=range(1,301),default=60)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--report',type=Path,default=Path('.local/audio-diagnostics.json'))
    args=parser.parse_args();watch(args.seconds,args.port,args.report)
