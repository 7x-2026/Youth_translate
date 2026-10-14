"""Only official generated types are used on the upstream wire."""
from dataclasses import dataclass
from backend.generated.products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse
from backend.generated.common import events_pb2 as E

LANGUAGES = {'auto': ('zhen', 'zhen'), 'zh-en': ('zh', 'en'), 'en-zh': ('en', 'zh')}

class RelayError(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def request(session_id, event, mode='auto', audio=b''):
    req = TranslateRequest()
    req.request_meta.SessionID = session_id
    req.event = event
    if event in (E.StartSession, E.TaskRequest):
        req.source_audio.format = 'wav'
        req.source_audio.codec = 'raw'
        req.source_audio.rate, req.source_audio.bits, req.source_audio.channel = 16000, 16, 1
    if event == E.StartSession:
        req.user.uid = 'local_classroom'
        req.request.mode = 's2t'
        req.request.source_language, req.request.target_language = LANGUAGES[mode]
    if audio:
        req.source_audio.binary_data = audio
    return req.SerializeToString()


def decode(data):
    if not isinstance(data, bytes):
        raise RelayError('protocol', '云端返回了非 Protobuf 二进制帧。')
    msg = TranslateResponse()
    try:
        msg.ParseFromString(data)
    except Exception:
        raise RelayError('protocol', '无法解码云端 Protobuf 消息。') from None
    if msg.response_meta.StatusCode not in (0, 20000000):
        raise cloud_error(msg)
    return msg


def cloud_error(msg):
    code = msg.response_meta.StatusCode
    # Only documented server/transient failures retry. Unknown failures stop.
    transient = code == 45000081 or 55000000 <= code <= 55099999
    return RelayError(f'cloud_{code}', f'云端会话失败（状态码 {code}）。请检查 API Key、参数、资源权限、余额与额度；未知错误请联系供应商。', transient)

@dataclass
class Segment:
    id: str
    text: str = ''
    revision: int = 0
    start: int | None = None
    end: int | None = None
    final: bool = False
    sequence: int = 0

class Normalizer:
    """Independent channels, no invented cross-channel pairing or timestamps."""
    def __init__(self, class_id, epoch, response_mode):
        if response_mode not in ('delta', 'snapshot'):
            raise RelayError('semantics_unverified', '请先用协议探测确认字幕 Response 语义，并配置 VOLC_SUBTITLE_RESPONSE_MODE。')
        self.class_id, self.epoch, self.mode = class_id, epoch, response_mode
        self.current = {}
        self.counter = {'source': 0, 'translation': 0}

    def feed(self, msg):
        mapping = {E.SourceSubtitleStart: ('source', 'start'), E.SourceSubtitleResponse: ('source', 'update'), E.SourceSubtitleEnd: ('source', 'end'), E.TranslationSubtitleStart: ('translation', 'start'), E.TranslationSubtitleResponse: ('translation', 'update'), E.TranslationSubtitleEnd: ('translation', 'end')}
        if msg.event not in mapping: return None
        channel, action = mapping[msg.event]
        # Live AST responses repeat Sequence for every text fragment in a segment.
        # It identifies the segment; using it to deduplicate frames loses almost all text.
        seq = msg.response_meta.Sequence
        seg = self.current.get(channel)
        if action == 'start':
            if seg and not seg.final and seg.start == msg.start_time and seg.sequence == seq: return None
            self.counter[channel] += 1
            seg = Segment(f'{channel}-{seq or self.counter[channel]}', start=msg.start_time, sequence=seq)
            self.current[channel] = seg
        elif seg is None or (seq and seg.sequence and seq != seg.sequence):
            self.counter[channel] += 1
            seg = Segment(f'{channel}-{seq or self.counter[channel]}', sequence=seq)
            self.current[channel] = seg
        elif seg.final:
            if action == 'end': return None
            self.counter[channel] += 1
            seg = Segment(f'{channel}-{seq or self.counter[channel]}', sequence=seq)
            self.current[channel] = seg
        if action == 'update':
            seg.text = seg.text + msg.text if self.mode == 'delta' else msg.text
        elif action == 'end':
            # End carries the complete segment per official event example.
            if msg.text: seg.text = msg.text
            seg.final, seg.start, seg.end = True, msg.start_time, msg.end_time
        seg.revision += 1
        result = dict(type='subtitle', classId=self.class_id, sessionEpoch=self.epoch, segmentId=seg.id, channel=channel, revision=seg.revision, text=seg.text, isFinal=seg.final)
        if seg.start is not None: result['startMs'] = seg.start
        if seg.end is not None: result['endMs'] = seg.end
        return result
