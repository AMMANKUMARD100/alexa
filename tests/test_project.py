import sys
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as app_module
from app import LocalServer
from assistant import AlexaPlusAssistant
from browser_automation import BrowserAutomation
from calculator import calculate, safe_expression
from config import Settings, get_zone
from database import Database
from scheduler import ScheduleError, Scheduler, calendar_file, extract_command, parse_datetime

class CoreTests(unittest.TestCase):
    def test_frontend_asset_extraction_preserves_markup(self):
        source = '<!doctype html><html><head><style data-anchor="x">body{}</style></head><body><script data-anchor="y">run()</script></body></html>'
        with tempfile.TemporaryDirectory() as tmp:
            old_base = app_module.BASE_DIR
            app_module.BASE_DIR = Path(tmp)
            try:
                with zipfile.ZipFile(Path(tmp)/'alexa-plus.artifact','w') as archive:
                    archive.writestr('index.html',source)
                app_module.ensure_frontend()
                root = Path(tmp)/'static'
                page = (root/'index.html').read_text()
                self.assertIn('<link rel="stylesheet" href="/style.css">',page)
                self.assertIn('<script src="/app.js" defer></script>',page)
                self.assertLess(page.index('stylesheet'),page.index('src="/app.js"'))
                self.assertNotIn('<style',page)
                self.assertNotIn('data-anchor="y"',page)
                self.assertEqual((root/'style.css').read_text(),'body{}')
                self.assertEqual((root/'app.js').read_text(),'run()')
            finally:
                app_module.BASE_DIR = old_base

    def test_natural_language_datetime(self):
        now = datetime(2026, 10, 25, 16, 0, tzinfo=get_zone('Asia/Kolkata'))
        self.assertEqual(parse_datetime('tomorrow at 3 PM','Asia/Kolkata',now).strftime('%Y-%m-%d %H:%M'), '2026-10-26 15:00')
        self.assertEqual(parse_datetime('next Monday at 10 AM','Asia/Kolkata',now).strftime('%Y-%m-%d %H:%M'), '2026-10-26 10:00')
        self.assertEqual(parse_datetime('in 30 minutes','Asia/Kolkata',now).strftime('%H:%M'), '16:30')
        self.assertEqual(parse_datetime('2027-10-25 at 15:00','Asia/Kolkata',now).year, 2027)
        with self.assertRaises(ScheduleError):
            parse_datetime('tomorrow afternoon','Asia/Kolkata',now)

    def test_dst_gap_is_not_silently_shifted(self):
        try:
            zone = get_zone('America/Chicago')
        except ValueError:
            self.skipTest('ZoneInfo data unavailable in this environment')
        from scheduler import localize
        with self.assertRaises(ScheduleError):
            localize(datetime(2025,3,9,2,30), zone)

    def test_command_extraction_and_reminder_time(self):
        self.assertEqual(extract_command('schedule a meeting called Team sync tomorrow at 2 PM'),('meeting','Team sync','tomorrow at 2 PM'))
        self.assertEqual(extract_command('remind me to call John in 30 minutes'),('reminder','call John','in 30 minutes'))

    def test_database_and_due_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'test.db')
            start=1_800_000_000
            event_id=db.add('reminder','Stretch',start,start,start,'UTC')
            self.assertEqual(db.get(event_id)['title'],'Stretch')
            self.assertEqual(db.notifications(),[])
            db.queue_due(start)
            notes=db.notifications()
            self.assertEqual(notes[0]['message'],'Reminder: Stretch')
            self.assertTrue(db.acknowledge(notes[0]['id']))
            self.assertEqual(db.notifications(),[])

    def test_concurrent_database_inserts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'threads.db')
            errors=[]
            def insert(n):
                try: db.add('reminder',str(n),2_000_000_000,2_000_000_000,2_000_000_000,'UTC')
                except Exception as exc: errors.append(exc)
            threads=[threading.Thread(target=insert,args=(n,)) for n in range(20)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertEqual(errors,[])
            self.assertEqual(len(db.upcoming(1_900_000_000)),20)

    def test_ics_escapes_and_emits_utc(self):
        event={'id':1,'created_at':1_700_000_000,'starts_at':1_800_000_000,'ends_at':1_800_003_600,
               'title':'Plan; review, notes\nnext','location':'Office, floor 2'}
        data=calendar_file(event).decode()
        self.assertIn('SUMMARY:Plan\\; review\\, notes\\nnext',data)
        self.assertIn('DTSTART:20270115T080000Z',data)
        self.assertTrue(data.endswith('END:VCALENDAR\r\n'))

    def test_calculator_is_bounded_and_no_eval(self):
        self.assertEqual(calculate('calculate 15% of 8500'),'1275')
        self.assertEqual(calculate('square root of 144'),'12')
        self.assertEqual(calculate('2^8'),'256')
        self.assertIsNone(calculate('explain the square root of a number'))
        with self.assertRaises((ValueError,SyntaxError)):
            safe_expression('__import__("os").system("echo bad")')

    def test_allowlisted_browser_intents(self):
        browser=BrowserAutomation()
        self.assertEqual(browser.parse_command('open youtube and search for india'),('youtube','india'))
        result=browser.execute_command('search for Python tutorials on Google')
        self.assertIn('https://www.google.com/search?q=Python+tutorials',result['action']['url'])
        result=browser.execute_command('open calculator')
        self.assertIn('not enabled',result['text'])
        self.assertNotIn('action',result)
        self.assertIsNone(browser.execute_command('run something'))

    def test_local_clock_does_not_query_wikipedia(self):
        with tempfile.TemporaryDirectory() as tmp:
            assistant=AlexaPlusAssistant(Settings(database=Path(tmp)/'clock.db'))
            events=list(assistant.stream('what time is it'))
            assistant.cleanup()
            self.assertFalse(any(e[0]=='notice' and 'Wikipedia' in e[1].get('text','') for e in events))
            self.assertEqual(events[0][0],'delta')
            self.assertRegex(events[0][1]['text'],r'\d{1,2}:\d{2} (?:AM|PM)')
            self.assertEqual(events[1][1]['source'],'Local clock')

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        assistant=AlexaPlusAssistant(Settings(database=Path(self.tmp.name)/'http.db'))
        try:
            self.server=LocalServer(('127.0.0.1',0),assistant)
        except OSError as exc:
            self.skipTest('Loopback sockets unavailable in this environment: '+str(exc))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        with urlopen(self.url+'/api/bootstrap',timeout=2) as r:self.csrf=r.read().decode()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.server.assistant.cleanup();self.thread.join(timeout=2);self.tmp.cleanup()

    def post(self,path,payload,origin=None,token=None):
        headers={'Content-Type':'application/json','Origin':origin or self.url,'X-Assistant-Token':token or __import__('json').loads(self.csrf)['csrf']}
        return Request(self.url+path,data=__import__('json').dumps(payload).encode(),headers=headers,method='POST')

    def test_local_schedule_http_roundtrip(self):
        import json
        request=self.post('/api/events',{'title':'HTTP test','kind':'meeting','when':'in 2 hours','duration':30,'location':''})
        with urlopen(request,timeout=3) as response:
            self.assertEqual(response.status,201)
            self.assertEqual(json.loads(response.read())['event']['title'],'HTTP test')
        with urlopen(self.url+'/api/state',timeout=2) as response:
            self.assertEqual(json.loads(response.read())['events'][0]['title'],'HTTP test')

    def test_rejects_cross_origin_and_bad_token(self):
        request=self.post('/api/events',{'title':'bad','when':'in 2 hours'},origin='http://evil.example')
        with self.assertRaises(HTTPError) as cm:urlopen(request,timeout=2)
        self.assertEqual(cm.exception.code,403)
        request=self.post('/api/events',{'title':'bad','when':'in 2 hours'},token='wrong')
        with self.assertRaises(HTTPError) as cm:urlopen(request,timeout=2)
        self.assertEqual(cm.exception.code,403)

if __name__=='__main__': unittest.main()
