"""Local, transactionally saved course text. Never stores audio or credentials."""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

STATES = {'connecting': 'recording', 'running': 'recording', 'muted': 'recording',
          'recovering': 'recording', 'finishing': 'recording', 'paused': 'paused',
          'stopped': 'ended', 'error': 'interrupted'}


class RecordStore:
    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.lock = threading.RLock()
        self.db = None

    def _connection(self):
        if self.db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=2, check_same_thread=False)
            try:
                db.row_factory = sqlite3.Row
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA synchronous=FULL')
                db.execute('PRAGMA foreign_keys=ON')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS daily_numbers (
                        day TEXT PRIMARY KEY, number INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS courses (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                        day TEXT NOT NULL, number INTEGER NOT NULL,
                        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                        state TEXT NOT NULL, mode TEXT NOT NULL, engine TEXT NOT NULL,
                        incomplete INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(day, number)
                    );
                    CREATE TABLE IF NOT EXISTS segments (
                        position INTEGER PRIMARY KEY AUTOINCREMENT,
                        course_id TEXT NOT NULL REFERENCES courses(id),
                        epoch INTEGER NOT NULL, channel TEXT NOT NULL,
                        segment_id TEXT NOT NULL, revision INTEGER NOT NULL,
                        text TEXT NOT NULL, is_final INTEGER NOT NULL,
                        received_at INTEGER NOT NULL,
                        UNIQUE(course_id, epoch, channel, segment_id)
                    );
                ''')
                db.commit()
                self.db = db
            except BaseException:
                db.close()
                raise
        return self.db

    @staticmethod
    def _course(row):
        return dict(id=row['id'], name=row['name'], createdAt=row['created_at'],
                    updatedAt=row['updated_at'], state=row['state'], mode=row['mode'],
                    engine=row['engine'], incomplete=bool(row['incomplete']))

    def save_event(self, event, mode='auto', engine='standard', incomplete=False):
        class_id = event.get('classId')
        subtitle = event.get('type') == 'subtitle'
        state = STATES.get(event.get('state')) if event.get('type') == 'status' else None
        if not class_id or (not subtitle and state is None):
            return None
        now = self.clock()
        timestamp = int(now.timestamp() * 1000)
        with self.lock:
            db = self._connection()
            with db:
                db.execute('BEGIN IMMEDIATE')
                course = db.execute('SELECT * FROM courses WHERE id=?', (class_id,)).fetchone()
                if course is None:
                    # Pausing/stopping an unused relay must not create empty courses.
                    if not subtitle and state != 'recording':
                        return None
                    day = now.strftime('%Y-%m-%d')
                    db.execute('''INSERT INTO daily_numbers(day, number) VALUES (?, 1)
                        ON CONFLICT(day) DO UPDATE SET number=number+1''', (day,))
                    number = db.execute('SELECT number FROM daily_numbers WHERE day=?', (day,)).fetchone()[0]
                    name = f'{day}-{number:03d}'
                    db.execute('''INSERT INTO courses
                        (id,name,day,number,created_at,updated_at,state,mode,engine,incomplete)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
                        (class_id, name, day, number, timestamp, timestamp, 'recording', mode, engine, int(incomplete)))
                if subtitle:
                    db.execute('''INSERT INTO segments
                        (course_id,epoch,channel,segment_id,revision,text,is_final,received_at)
                        VALUES (?,?,?,?,?,?,?,?)
                        ON CONFLICT(course_id,epoch,channel,segment_id) DO UPDATE SET
                            revision=excluded.revision,text=excluded.text,
                            is_final=excluded.is_final,received_at=excluded.received_at
                        WHERE excluded.revision>segments.revision AND segments.is_final=0''',
                        (class_id, event['sessionEpoch'], event['channel'], event['segmentId'],
                         event['revision'], event['text'], int(event['isFinal']), timestamp))
                db.execute('''UPDATE courses SET updated_at=?,state=COALESCE(?,state),
                    mode=?,incomplete=MAX(incomplete,?) WHERE id=?''',
                    (timestamp, state, mode, int(incomplete), class_id))
                result = self._course(db.execute('SELECT * FROM courses WHERE id=?', (class_id,)).fetchone())
            return result

    def interrupt(self, class_id, incomplete=False):
        with self.lock:
            db = self._connection()
            with db:
                db.execute("""UPDATE courses SET state=CASE WHEN state='recording' THEN 'interrupted' ELSE state END,
                    incomplete=MAX(incomplete,?) WHERE id=?""", (int(incomplete), class_id))

    def list_courses(self, limit=50, offset=0):
        with self.lock:
            rows = self._connection().execute('''SELECT courses.*,
                (SELECT COUNT(*) FROM segments WHERE course_id=courses.id AND text!='') AS count
                FROM courses ORDER BY created_at DESC,number DESC LIMIT ? OFFSET ?''', (limit + 1, offset)).fetchall()
            return dict(records=[dict(self._course(row), segmentCount=row['count']) for row in rows[:limit]], hasMore=len(rows) > limit)

    def get_course(self, class_id):
        with self.lock:
            db = self._connection()
            row = db.execute('SELECT * FROM courses WHERE id=?', (class_id,)).fetchone()
            if row is None:
                return None
            segments = db.execute("SELECT * FROM segments WHERE course_id=? AND text!='' ORDER BY position", (class_id,)).fetchall()
            entries = [dict(type='subtitle', classId=class_id, sessionEpoch=s['epoch'],
                            channel=s['channel'], segmentId=s['segment_id'], revision=s['revision'],
                            text=s['text'], isFinal=bool(s['is_final']), unfinished=not s['is_final'],
                            receivedAt=s['received_at']) for s in segments]
            return dict(record=dict(self._course(row), segmentCount=len(entries)), entries=entries)

    def export_text(self, class_id):
        result = self.get_course(class_id)
        if result is None:
            return None
        course = result['record']
        lines = [f"课堂记录：{course['name']}"]
        if course['incomplete']:
            lines.append('注意：本次课程曾发生保存失败，记录可能不完整。')
        for entry in result['entries']:
            time = datetime.fromtimestamp(entry['receivedAt'] / 1000).astimezone().strftime('%H:%M:%S')
            channel = '原文' if entry['channel'] == 'source' else '译文'
            unfinished = '（未定稿）' if entry['unfinished'] else ''
            lines.append(f"[{time}] {channel}{unfinished}\n{entry['text']}")
        return course['name'], '\n\n'.join(lines)

    def close(self):
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None
