"""Local-only threaded HTTP/SSE server. Not intended for public deployment."""
import hmac
import json
import logging
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile
import re
from assistant import AlexaPlusAssistant
from config import BASE_DIR, Settings
from scheduler import ScheduleError, calendar_file

MAX_BODY = 65536


def ensure_frontend():
    """Build same-origin static assets from the bundled UI preview on first launch."""
    destination = BASE_DIR / 'static'
    index_path = destination / 'index.html'
    style_path = destination / 'style.css'
    script_path = destination / 'app.js'
    if all(path.is_file() for path in (index_path, style_path, script_path)):
        return
    bundle = BASE_DIR / 'alexa-plus.artifact'
    try:
        with ZipFile(bundle) as archive:
            html = archive.read('index.html').decode('utf-8')
    except (OSError, KeyError, UnicodeDecodeError, BadZipFile) as exc:
        raise RuntimeError('The bundled alexa-plus.artifact frontend is missing or invalid.') from exc
    style = re.search(r'<style(?:\s[^>]*)?>(.*?)</style\s*>', html, re.I | re.S)
    script = re.search(r'<script(?:\s[^>]*)?>(.*?)</script\s*>', html, re.I | re.S)
    if not style or not script:
        raise RuntimeError('The bundled frontend is missing its stylesheet or application script.')
    script_tag = '<script src="/app.js" defer></script>'
    html = html[:script.start()] + script_tag + html[script.end():]
    html = html[:style.start()] + '<link rel="stylesheet" href="/style.css">' + html[style.end():]
    destination.mkdir(parents=True, exist_ok=True)
    index_path.write_text(html, encoding='utf-8')
    style_path.write_text(style.group(1), encoding='utf-8')
    script_path.write_text(script.group(1), encoding='utf-8')


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, assistant):
        super().__init__(address, Handler)
        self.assistant = assistant
        self.token = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(4)
        self.allowed_hosts = {f'127.0.0.1:{self.server_port}',f'localhost:{self.server_port}'}
        self.origins = {'http://'+host for host in self.allowed_hosts}

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Deliberately do not log request paths, prompts, request bodies or keys.
        logging.info('%s %s',self.command,args[1] if len(args)>1 else '')

    def valid_host(self):
        if self.headers.get('Host') not in self.server.allowed_hosts:
            self.reply(403,{'error':'This service accepts only localhost requests.'})
            return False
        return True

    def headers_common(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def reply(self, status, data, mime='application/json; charset=utf-8'):
        body = json.dumps(data).encode() if not isinstance(data,bytes) else data
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        a = self.server.assistant
        if path=='/api/bootstrap':
            self.reply(200,{'csrf':self.server.token,'groq_configured':a.qa.fast_qa.available,
                            'model':a.settings.model,'timezone':a.settings.timezone})
        elif path=='/api/state':
            self.reply(200,{'events':a.db.upcoming(),'notifications':a.db.notifications()})
        elif path.startswith('/api/calendar/'):
            try:
                event = a.db.get(int(path.rsplit('/',1)[-1]))
                if not event or event['kind']!='meeting' or event['status']!='scheduled':
                    raise ValueError()
                self.reply(200,calendar_file(event),'text/calendar; charset=utf-8')
            except ValueError:
                self.reply(404,{'error':'Meeting not found.'})
        elif path in ('/','/app.js','/style.css'):
            name = 'index.html' if path=='/' else path[1:]
            file = BASE_DIR/'static'/name
            if not file.exists():
                self.reply(404,{'error':'Frontend file missing. Extract the entire project.'})
            else:
                mime = {'html':'text/html','js':'text/javascript','css':'text/css'}[name.split('.')[-1]]
                self.reply(200,file.read_bytes(),mime+'; charset=utf-8')
        else:
            self.reply(404,{'error':'Not found.'})

    def read_body(self):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Chunked requests are not supported.')
        if not self.headers.get('Content-Type','').startswith('application/json'):
            raise ValueError('Use application/json.')
        length = int(self.headers.get('Content-Length','0'))
        if not 0 < length <= MAX_BODY:
            raise ValueError('Invalid request size.')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data,dict):
            raise ValueError('Expected a JSON object.')
        return data

    def do_POST(self):
        self.connection.settimeout(30)
        if not self.valid_host():
            self.close_connection = True
            return
        if self.headers.get('Origin') not in self.server.origins or not hmac.compare_digest(self.headers.get('X-Assistant-Token',''),self.server.token):
            self.reply(403,{'error':'Invalid origin or session token. Reload the assistant page.'})
            self.close_connection = True
            return
        try:
            body = self.read_body()
            path = urlsplit(self.path).path
            a = self.server.assistant
            if path=='/api/chat':
                message = body.get('message','')
                history = body.get('history',[])
                if not isinstance(message,str) or not 1<=len(message.strip())<=4000:
                    raise ValueError('Use a message of 1–4000 characters.')
                if not isinstance(history,list) or len(history)>10 or any(not isinstance(x,dict) for x in history):
                    raise ValueError('Invalid conversation history.')
                if not self.server.slots.acquire(blocking=False):
                    self.reply(429,{'error':'The assistant is busy. Please try again shortly.'})
                    return
                try:
                    self.send_response(200)
                    self.headers_common()
                    self.send_header('Content-Type','text/event-stream; charset=utf-8')
                    self.send_header('Connection','close')
                    self.send_header('X-Accel-Buffering','no')
                    self.end_headers()
                    self.close_connection = True
                    try:
                        for kind, payload in a.stream(message,history,body.get('grounded') is True):
                            self.emit(kind,payload)
                    except (BrokenPipeError,ConnectionResetError):
                        return
                    except Exception:
                        logging.exception('Command failed')
                        self.emit('error',{'text':'The command failed unexpectedly. Check the terminal and retry.'})
                finally:
                    self.server.slots.release()
            elif path=='/api/events':
                event, overlaps = a.scheduler.create(body.get('title',''),body.get('when',''),body.get('kind','meeting'),body.get('duration',30),body.get('location',''))
                self.reply(201,{'event':event,'overlaps':len(overlaps)})
            elif path=='/api/cancel':
                if body.get('confirmed') is not True:
                    raise ValueError('Confirm cancellation first.')
                ok = a.db.cancel(int(body['id']))
                self.reply(200 if ok else 404,{'cancelled':ok})
            elif path=='/api/ack':
                self.reply(200,{'acknowledged':a.db.acknowledge(int(body['id']))})
            else:
                self.reply(404,{'error':'Not found.'})
        except (ValueError,TypeError,KeyError,ScheduleError) as e:
            self.reply(400,{'error':str(e) or 'Invalid request.'})
            self.close_connection = True
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            self.close_connection = True
        except Exception:
            logging.exception('Request failed')
            self.reply(500,{'error':'Local server error. Check the terminal.'})

    def emit(self, kind, payload):
        packet = f'event: {kind}\ndata: {json.dumps(payload,ensure_ascii=False)}\n\n'.encode()
        self.wfile.write(packet)
        self.wfile.flush()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Alexa Plus local assistant')
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(levelname)s: %(message)s')
    assistant = AlexaPlusAssistant(Settings.from_env())
    ensure_frontend()
    server = LocalServer(('127.0.0.1',assistant.settings.port),assistant)
    assistant.scheduler.start()
    url = f'http://127.0.0.1:{server.server_port}'
    print('\nAlexa Plus: '+url)
    print('Groq key configured (not yet verified): '+str(assistant.qa.fast_qa.available))
    print('Local-only server. Keep this terminal open for reminders. Ctrl+C stops it.\n')
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\nStopping…')
    finally:
        assistant.cleanup()
        server.server_close()

if __name__=='__main__':
    main()
