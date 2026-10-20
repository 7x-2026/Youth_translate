"""Check native audio levels locally. Prints statistics only; no files and no cloud calls."""
import argparse
import array
import asyncio
import json
import math
from backend.system_audio import SystemAudio


async def check(seconds):
    capture = SystemAudio()
    count, power, peak = 0, 0., 0.
    remainder = b''
    try:
        ready = await capture.open()
        print(json.dumps(ready, ensure_ascii=False), flush=True)
        try:
            async with asyncio.timeout(seconds):
                while True:
                    data = await capture.read()
                    if not data:
                        raise RuntimeError('系统音频组件已退出')
                    data = remainder + data
                    remainder = data[len(data)//2*2:]
                    values = array.array('h', data[:len(data)//2*2])
                    count += len(values)
                    power += sum((v/32768)**2 for v in values)
                    peak = max(peak, max((abs(v)/32768 for v in values), default=0))
        except TimeoutError:
            pass
        print(json.dumps(dict(samples=count, seconds=round(count/16000, 2),
            rms=round(math.sqrt(power/count), 6) if count else 0, peak=round(peak, 6)), ensure_ascii=False))
    finally:
        await capture.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=5, choices=range(1, 31))
    args = parser.parse_args()
    asyncio.run(check(args.seconds))
