"""Deterministic scheduling; reject ambiguous dates instead of guessing silently."""
import re
import threading
import logging
from datetime import datetime, timedelta, timezone
from config import get_zone

WEEKDAYS = 'monday tuesday wednesday thursday friday saturday sunday'.split()
DAY_PATTERN = '|'.join(WEEKDAYS)

class ScheduleError(ValueError):
    pass

def localize(naive, zone):
    a = naive.replace(tzinfo=zone, fold=0)
    b = naive.replace(tzinfo=zone, fold=1)
    valid = [x for x in (a,b) if x.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive]
    if not valid:
        raise ScheduleError('That local time does not exist because of daylight saving. Choose another time.')
    if len(valid) == 2 and a.utcoffset() != b.utcoffset():
        raise ScheduleError('That local time occurs twice because of daylight saving. Choose another time.')
    return valid[0]

def parse_datetime(text, zone_name, now=None):
    zone = get_zone(zone_name)
    now = (now or datetime.now(zone)).astimezone(zone)
    text = text.strip().lower().rstrip('.!?')
    relative = re.fullmatch(r'in\s+(\d{1,6})\s*(second|minute|hour|day|week)s?', text)
    if relative:
        n, unit = int(relative[1]), relative[2]
        seconds = n * {'second':1,'minute':60,'hour':3600,'day':86400,'week':604800}[unit]
        if not 1 <= seconds <= 366 * 86400:
            raise ScheduleError('Choose a relative time within the next 366 days.')
        return (now.astimezone(timezone.utc) + timedelta(seconds=seconds)).astimezone(zone)
    clock = re.search(r'(?:\bat\s+|\s|^)(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b', text)
    if not clock:
        raise ScheduleError('Please include a date and time, for example tomorrow at 3 PM.')
    h, minute, meridian = int(clock[1]), int(clock[2] or 0), clock[3]
    if minute > 59 or (meridian and not 1 <= h <= 12) or (not meridian and h > 23):
        raise ScheduleError('That is not a valid time.')
    if not meridian and clock[2] is None and h <= 12:
        raise ScheduleError('Please specify AM or PM, or use a 24-hour time such as 15:00.')
    if meridian:
        h = h % 12 + (12 if meridian == 'pm' else 0)
    date_text = (text[:clock.start()] + ' ' + text[clock.end():]).strip()
    date_text = re.sub(r'^(?:on|at)\s+', '', date_text)
    date_text = re.sub(r'\s+(?:on|at)$', '', date_text)
    date_text = re.sub(r'\s+', ' ', date_text).strip()
    base = now.date()
    explicit = bool(date_text)
    if date_text in ('', 'today'):
        pass
    elif date_text == 'tomorrow':
        base += timedelta(days=1)
    elif date_text == 'next week':
        base += timedelta(days=7)
    elif re.fullmatch(r'(?:next\s+)?(?:' + DAY_PATTERN + ')', date_text):
        day = WEEKDAYS.index(date_text.split()[-1])
        offset = (day - now.weekday()) % 7
        base += timedelta(days=offset or 7)
    else:
        parsed = None
        for fmt in ('%Y-%m-%d', '%B %d %Y', '%b %d %Y', '%B %d', '%b %d'):
            try:
                parsed = datetime.strptime(date_text.replace(',', ''), fmt).date()
                if '%Y' not in fmt:
                    parsed = parsed.replace(year=now.year)
                    if parsed < now.date():
                        parsed = parsed.replace(year=now.year+1)
                break
            except ValueError:
                continue
        if parsed is None:
            raise ScheduleError('Use today, tomorrow, next Monday, or a date such as 2027-10-25 at 15:00.')
        base = parsed
    result = localize(datetime.combine(base, datetime.min.time()).replace(hour=h, minute=minute), zone)
    if not explicit and result <= now:
        result = localize(result.replace(tzinfo=None) + timedelta(days=1), zone)
    if result <= now:
        raise ScheduleError('That time is in the past. Please choose a future time.')
    return result

def extract_command(command):
    command = command.strip().rstrip('.!?')
    cmd = re.sub(r'^(?:can\s+you\s+|please\s+)', '', command, flags=re.I).strip()
    if re.match(r'^(?:schedule|set|book|create)\s+(?:a\s+|an\s+)?(?:meeting|appointment)\b', cmd, re.I):
        kind = 'meeting'
        rest = re.sub(r'^(?:schedule|set|book|create)\s+(?:a\s+|an\s+)?(?:meeting|appointment)\s*', '', cmd, flags=re.I)
        rest = re.sub(r'^(?:for\s+me\s+)?(?:called|named|titled)?\s*', '', rest, flags=re.I).strip()
    elif re.match(r'^(?:schedule|set|create)\s+(?:a\s+)?reminder\b', cmd, re.I):
        kind = 'reminder'
        rest = re.sub(r'^(?:schedule|set|create)\s+(?:a\s+)?reminder\s*(?:to\s+)?', '', cmd, flags=re.I).strip()
    elif re.match(r'^remind\s+me\b', cmd, re.I):
        kind = 'reminder'
        rest = re.sub(r'^remind\s+me\s+(?:to\s+)?', '', cmd, flags=re.I).strip()
    else:
        return None

    # Handle voice syntax: remind me tomorrow at 9 am to call mom
    m_reverse = re.match(r'^((?:today|tomorrow|next\s+(?:week|' + DAY_PATTERN + r')|at\s+\d|\d{1,2}(?::\d{2})?\s*(?:am|pm)).+?)\s+to\s+(.+)$', rest, re.I)
    if m_reverse and kind == 'reminder':
        time_part, title = m_reverse.group(1).strip(), m_reverse.group(2).strip()
        return kind, title, time_part

    boundary = re.search(r'\b(?:today\b|tomorrow\b|next\s+(?:week|' + DAY_PATTERN + r')\b|on\s+|at\s+\d|(?:for\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)\b)|in\s+\d)', rest, re.I)
    if not boundary:
        raise ScheduleError('Include a title and time: schedule a meeting called Team sync tomorrow at 3 PM.')
    title = rest[:boundary.start()].strip(' \"\'')
    time_part = rest[boundary.start():].strip()
    time_part = re.sub(r'^for\s+(?=\d)', '', time_part, flags=re.I)
    if not title or title.lower() in ('for me', 'a meeting', 'meeting', 'an appointment', 'appointment', 'reminder'):
        title = 'Meeting' if kind == 'meeting' else 'Reminder'
    return kind, title, time_part

class Scheduler:
    def __init__(self, db, zone_name):
        self.db, self.zone_name = db, zone_name
        self.stop_event = threading.Event()
        self.thread = None

    def create(self, title, when, kind='meeting', duration=30, location=''):
        title, location = str(title).strip(), str(location).strip()
        if kind not in ('meeting','reminder') or not 1 <= len(title) <= 200 or len(location) > 300:
            raise ScheduleError('Use a title of 1–200 characters and a valid event type.')
        if isinstance(duration, bool) or not isinstance(duration, int) or not 5 <= duration <= 480:
            raise ScheduleError('Meeting duration must be 5–480 minutes.')
        if not isinstance(when, str) or len(when) > 120:
            raise ScheduleError('Please provide a valid date and time.')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', when):
            dt = localize(datetime.fromisoformat(when), get_zone(self.zone_name))
        else:
            dt = parse_datetime(when, self.zone_name)
        start = int(dt.timestamp())
        if start <= int(datetime.now(timezone.utc).timestamp()):
            raise ScheduleError('That time is in the past.')
        end = start + (duration * 60 if kind == 'meeting' else 0)
        overlaps = self.db.conflicts(start,end) if kind == 'meeting' else []
        notify = max(int(datetime.now(timezone.utc).timestamp()), start-900) if kind == 'meeting' else start
        event_id = self.db.add(kind,title,start,end,notify,self.zone_name,location)
        return self.db.get(event_id), overlaps

    def from_command(self, command):
        parsed = extract_command(command)
        if parsed is None:
            return None
        kind, title, when = parsed
        event, overlaps = self.create(title,when,kind)
        stamp = datetime.fromtimestamp(event['starts_at'], get_zone(self.zone_name)).strftime('%a, %d %b %Y at %I:%M %p')
        text = f"{'Meeting scheduled' if kind == 'meeting' else 'Reminder set'}: {title}, {stamp} ({self.zone_name})."
        if kind == 'meeting':
            text += ' A local reminder is due 15 minutes before, or now if the meeting is sooner. No invitations have been sent.'
        if overlaps:
            text += ' Warning: this overlaps another meeting.'
        return {'text':text, 'source':'Local schedule', 'event':event}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True, name='reminders')
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.db.queue_due()
            except Exception:
                logging.exception('Reminder queue failed')
            self.stop_event.wait(1)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

def calendar_file(event):
    def esc(s):
        return str(s).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    def utc(ts):
        return datetime.fromtimestamp(ts,timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Alexa Plus Local//EN','CALSCALE:GREGORIAN',
             'BEGIN:VEVENT',f"UID:alexa-plus-{event['id']}-{event['created_at']}@localhost",
             'DTSTAMP:'+utc(event['created_at']),'DTSTART:'+utc(event['starts_at']),
             'DTEND:'+utc(max(event['ends_at'],event['starts_at']+60)),
             'SUMMARY:'+esc(event['title']),'LOCATION:'+esc(event['location']),
             'DESCRIPTION:'+esc('Created in Alexa Plus. Importing does not send invitations.'),'END:VEVENT','END:VCALENDAR']
    # RFC 5545 folding is byte-based; never split a UTF-8 character.
    folded = []
    for line in lines:
        chunk = ''
        for char in line:
            if len((chunk+char).encode('utf-8')) > 73:
                folded.append(chunk)
                chunk = ' '
            chunk += char
        folded.append(chunk)
    return ('\r\n'.join(folded)+'\r\n').encode('utf-8')
