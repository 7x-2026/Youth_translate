"""Windows shared-mode WASAPI loopback worker. stdout is header + PCM16, never playback."""
import json
import sys
import argparse


def outputs(soundcard):
    default = soundcard.default_speaker()
    return [dict(id=s.id, label=s.name, isDefault=default is not None and s.id == default.id)
            for s in soundcard.all_speakers()]


def capture(soundcard, numpy, output, device_id=None):
    speaker = soundcard.get_speaker(id=device_id) if device_id else soundcard.default_speaker()
    if device_id and speaker.id != device_id:
        raise RuntimeError('所选声音输出设备已断开')
    if speaker is None:
        raise RuntimeError('没有默认声音输出设备')
    loopback = soundcard.get_microphone(id=speaker.id, include_loopback=True)
    # Record all channels, then mix down: WASAPI's single-channel path can return corrupt samples.
    # Shared mode preserves the meeting's use of the output device.
    with loopback.recorder(samplerate=16000, channels=None, blocksize=1280, exclusive_mode=False) as recorder:
        header = dict(type='ready', sampleRate=16000, label=speaker.name)
        output.write((json.dumps(header, ensure_ascii=False) + '\n').encode('utf-8'))
        output.flush()
        while True:
            data = recorder.record(numframes=640)
            mono = numpy.nan_to_num(data.mean(axis=1), nan=0, posinf=0, neginf=0)
            mono = numpy.clip(mono, -1, 1)
            pcm = numpy.rint(mono * numpy.where(mono < 0, 32768, 32767)).astype('<i2')
            output.write(pcm.tobytes())
            output.flush()


if __name__ == '__main__':
    try:
        import soundcard
        import numpy
        parser = argparse.ArgumentParser()
        parser.add_argument('--list', action='store_true')
        parser.add_argument('--device')
        args = parser.parse_args()
        if args.list:
            print(json.dumps(outputs(soundcard), ensure_ascii=False))
        else:
            capture(soundcard, numpy, sys.stdout.buffer, args.device)
    except (Exception, KeyboardInterrupt):
        sys.exit(2)
