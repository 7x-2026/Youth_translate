"""In-memory transport timings and levels. No audio, transcripts or credentials."""
import array
import math
import sys
import time


class AudioDiagnostics:
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.received=self.sent=0
        self.last_received=self.last_sent=self.first_sound=None
        self.first_source=self.first_translation=None
        self.last_source=self.last_translation=None
        self.rms_dbfs=None
        self.cloud_muted_ms=None

    @staticmethod
    def power(packet):
        values=array.array('h',packet)
        if sys.byteorder!='little':values.byteswap()
        return sum(v*v for v in values)/len(values) if values else 0

    def receive(self,packet):
        self.received+=len(packet);self.last_received=self.clock()
        power=self.power(packet)
        self.rms_dbfs=round(10*math.log10(power/(32768**2)),1) if power else None

    def send(self,packet):
        self.sent+=len(packet);self.last_sent=self.clock()
        # Signal activity, not a speech detector. Never drives automatic retries.
        if self.first_sound is None and self.power(packet)>10000:self.first_sound=self.last_sent

    def subtitle(self,channel):
        now=self.clock()
        if channel=='source':
            self.last_source=now
            if self.first_source is None:self.first_source=now
        else:
            self.last_translation=now
            if self.first_translation is None:self.first_translation=now

    def snapshot(self):
        now=self.clock()
        age=lambda t:None if t is None else round((now-t)*1000)
        delay=lambda t:None if t is None or self.first_sound is None else round((t-self.first_sound)*1000)
        return dict(receivedAudioMs=self.received/32,sentToCloudAudioMs=self.sent/32,
            lastReceivedAgoMs=age(self.last_received),lastSentToCloudAgoMs=age(self.last_sent),
            lastInputDbfs=self.rms_dbfs,cloudMutedDurationMs=self.cloud_muted_ms,
            firstSourceAfterSoundMs=delay(self.first_source),firstTranslationAfterSoundMs=delay(self.first_translation),
            lastSourceAgoMs=age(self.last_source),lastTranslationAgoMs=age(self.last_translation))
