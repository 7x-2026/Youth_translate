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


def main(argv=None):
    try:
        import soundcard
        import numpy
        parser = argparse.ArgumentParser()
        parser.add_argument('--list', action='store_true')
        parser.add_argument('--list-and-wait', action='store_true')
        parser.add_argument('--device')
        args = parser.parse_args(argv)
        if args.list or args.list_and_wait:
            sys.stdout.buffer.write((json.dumps(outputs(soundcard), ensure_ascii=False) + '\n').encode('utf-8'))
            sys.stdout.buffer.flush()
            if args.list_and_wait:
                # Loading/enumerating does not open a recorder. The parent sends
                # exactly one selected device after the user starts capture.
                line = sys.stdin.buffer.readline(16385)
                if not line:
                    return 0
                if len(line) > 16384 or not line.endswith(b'\n'):
                    raise ValueError('invalid capture command')
                command = json.loads(line)
                if not isinstance(command, dict) or set(command) != {'device'}:
                    raise ValueError('invalid capture command')
                device = command['device']
                if device is not None and (not isinstance(device, str) or not device or len(device) > 2048):
                    raise ValueError('invalid capture device')
                capture(soundcard, numpy, sys.stdout.buffer, device)
        else:
            capture(soundcard, numpy, sys.stdout.buffer, args.device)
        return 0
    except (Exception, KeyboardInterrupt):
        return 2


if __name__ == '__main__':
    sys.exit(main())
