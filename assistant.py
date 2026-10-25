"""Intent routing shared by the web server and CLI. Run this file for text mode."""
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from config import Settings, get_zone
from database import Database
from scheduler import Scheduler, ScheduleError
from browser_automation import BrowserAutomation
from question_answering import QuestionAnswering

SYSTEM_APPS = {
    'notepad': 'notepad.exe',
    'calculator': 'calc.exe',
    'calc': 'calc.exe',
    'cmd': 'cmd.exe',
    'command prompt': 'cmd.exe',
    'powershell': 'powershell.exe',
    'terminal': 'wt.exe',
    'explorer': 'explorer.exe',
    'file explorer': 'explorer.exe',
    'files': 'explorer.exe',
    'settings': 'ms-settings:',
    'paint': 'mspaint.exe',
    'mspaint': 'mspaint.exe',
    'task manager': 'taskmgr.exe',
    'taskmgr': 'taskmgr.exe',
    'chrome': 'chrome.exe',
    'firefox': 'firefox.exe',
    'edge': 'msedge.exe',
    'camera': 'microsoft.windows.camera:',
    'wordpad': 'write.exe',
    'control panel': 'control.exe',
}

def execute_system_task(command):
    cmd = command.strip().rstrip('.!?')
    match = re.match(r'^(?:open|launch|start|run)\s+(.+)$', cmd, re.I)
    if not match:
        return None
    target = match.group(1).strip()
    target_clean = re.sub(r'^(?:the\s+|a\s+|an\s+)?(?:app\s+named\s+|app\s+called\s+|application\s+named\s+|app\s+|application\s+)?', '', target, flags=re.I).strip()
    target_clean = re.sub(r'^(?:named|called)\s+', '', target_clean, flags=re.I).strip()
    key = target_clean.lower()
    
    app_to_launch = SYSTEM_APPS.get(key)
    if not app_to_launch:
        which = shutil.which(target_clean) or shutil.which(f'{target_clean}.exe')
        if which:
            app_to_launch = which
        elif sys.platform == 'win32' and re.match(r'^[a-zA-Z0-9_\-\.:\\]+$', target_clean):
            app_to_launch = target_clean

    if app_to_launch:
        try:
            if sys.platform == 'win32':
                os.startfile(app_to_launch)
            else:
                subprocess.Popen([app_to_launch])
            return {'text': f'Opening {target_clean} on your laptop.', 'source': 'System Action'}
        except Exception as e:
            return {'text': f'Could not open {target_clean}: {str(e)}', 'source': 'System Action'}
    return None

class AlexaPlusAssistant:
    def __init__(self, settings=None):
        self.settings = settings or Settings.from_env()
        self.db = Database(self.settings.database)
        self.scheduler = Scheduler(self.db,self.settings.timezone)
        self.browser = BrowserAutomation()
        self.qa = QuestionAnswering(self.settings)

    def stream(self, command, history=None, grounded=False):
        started = time.monotonic()
        command = command.strip()
        result = None
        try:
            if command.lower() in ('hello','hi','hey','help'):
                result = {'text':'Hi! Ask a question, say “open YouTube and search for India”, or “schedule a meeting called Team sync tomorrow at 3 PM”. Use the microphone for voice input.','source':'Assistant'}
            elif re.fullmatch(r'(?:what(?:\'s| is) (?:the )?(?:current )?time(?: now)?|what time is it|time)', command, re.I):
                result = {'text':datetime.now(get_zone(self.settings.timezone)).strftime('%I:%M %p')+' · '+self.settings.timezone,'source':'Local clock'}
            elif re.fullmatch(r'(?:what(?:\'s| is) (?:the )?date(?: today)?|(?:what )?day is (?:it|today)|date)',command,re.I):
                result = {'text':datetime.now(get_zone(self.settings.timezone)).strftime('%A, %d %B %Y'),'source':'Local clock'}
            elif re.fullmatch(r'(?:list(?: my)? meetings|show(?: my)? (?:meetings|schedule)|my meetings|what meetings do i have)\??',command,re.I):
                events = [e for e in self.db.upcoming() if e['kind']=='meeting']
                lines = [e['title']+' — '+datetime.fromtimestamp(e['starts_at'],get_zone(self.settings.timezone)).strftime('%d %b, %I:%M %p') for e in events]
                result = {'text':'\n'.join(lines) if lines else 'You have no upcoming meetings.','source':'Local schedule'}
            else:
                result = self.scheduler.from_command(command)
                if result is None:
                    browser_res = self.browser.execute_command(command)
                    if browser_res and browser_res.get('action'):
                        result = browser_res
                    else:
                        result = execute_system_task(command) or browser_res
        except ScheduleError as e:
            result = {'text':str(e),'source':'Scheduling clarification'}
        if result:
            yield 'delta', {'text':result['text']}
            yield 'meta', {'source':result.get('source','Local'),'sources':[]}
            if result.get('action'):
                yield 'action', result['action']
            if result.get('event'):
                yield 'saved', {'event':result['event']}
        else:
            yield from self.qa.answer(command,history,grounded)
        yield 'done', {'elapsed_ms':round((time.monotonic()-started)*1000)}

    def cleanup(self):
        self.scheduler.stop()

def main():
    assistant = AlexaPlusAssistant()
    assistant.scheduler.start()
    print('Alexa Plus — text mode. For the voice-enabled web UI run: python app.py')
    try:
        while True:
            command = input('\nYou: ').strip()
            if command.lower() in ('exit','quit','goodbye'):
                break
            if not command:
                continue
            for kind,data in assistant.stream(command):
                if kind=='delta':
                    print(data['text'],end='',flush=True)
                elif kind=='notice':
                    print('\nNotice: '+data['text'])
                elif kind=='action':
                    print('\nOpen this link: '+data['url'])
            assistant.db.queue_due()
            for notification in assistant.db.notifications():
                print('\n'+notification['message'])
                assistant.db.acknowledge(notification['id'])
            print()
    except (KeyboardInterrupt,EOFError):
        print('\nGoodbye.')
    finally:
        assistant.cleanup()

if __name__=='__main__':
    main()
