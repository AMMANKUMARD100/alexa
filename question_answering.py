"""Stream answers with provenance, opt-in Wikipedia grounding and honest fallbacks."""
import json
import re
import time
import threading
from collections import OrderedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from fast_qa import FastQA, ProviderError
from calculator import calculate

class Wikipedia:
    def __init__(self):
        self.cache, self.lock = OrderedDict(), threading.Lock()

    def lookup(self, question):
        query = re.sub(r'^(?:what is|what are|who is|tell me about|explain)\s+', '',question.strip(),flags=re.I).rstrip(' ?')
        key = query.casefold()
        with self.lock:
            saved = self.cache.get(key)
            if saved and saved[0] > time.monotonic():
                return saved[1]
        params = {'action':'query','format':'json','generator':'search','gsrsearch':query,
                  'gsrnamespace':0,'gsrlimit':1,'prop':'extracts|info','exintro':1,
                  'explaintext':1,'exchars':4500,'inprop':'url','redirects':1}
        req = Request('https://en.wikipedia.org/w/api.php?'+urlencode(params),
                      headers={'User-Agent':'AlexaPlusLocal/2.0 (personal educational assistant)'})
        with urlopen(req,timeout=5) as response:
            raw = response.read(400001)
            if len(raw)>400000:
                raise ValueError('Wikipedia response too large.')
            data = json.loads(raw)
        pages = data.get('query',{}).get('pages',{})
        result = None
        for page in pages.values():
            extract, url = page.get('extract','').strip(),page.get('fullurl','')
            if extract and url.startswith('https://en.wikipedia.org/'):
                result = {'title':page['title'],'url':url,'extract':extract[:4500]}
                break
        with self.lock:
            self.cache[key] = (time.monotonic()+600,result)
            self.cache.move_to_end(key)
            while len(self.cache)>128:
                self.cache.popitem(last=False)
        return result

class QuestionAnswering:
    def __init__(self,settings):
        self.fast_qa, self.wikipedia = FastQA(settings), Wikipedia()
        self.model = settings.model

    def answer(self,question,history=None,grounded=False):
        value = calculate(question)
        if value is not None:
            yield 'delta', {'text':value}
            yield 'meta', {'source':'Local calculator','sources':[]}
            return
        if re.search(r'\b(?:latest|weather|breaking news|stock price)\b|\bcurrent (?:president|prime minister|ceo|price)|\btoday[\'’]s\b',question,re.I):
            yield 'delta', {'text':'I cannot verify live news, weather or prices with this setup. I can open a web search so you can check an up-to-date source.'}
            yield 'meta', {'source':'Live-data limitation','sources':[]}
            yield 'action', {'url':'https://www.google.com/search?'+urlencode({'q':question}), 'label':'Check live web results'}
            return
        page = None
        if grounded or not self.fast_qa.available:
            try:
                page = self.wikipedia.lookup(question)
            except Exception:
                yield 'notice', {'text':'Wikipedia could not be reached. No encyclopedia source was retrieved.'}
        source_list = [{'title':page['title'],'url':page['url']}] if page else []
        if self.fast_qa.available:
            output = False
            try:
                for token in self.fast_qa.stream(question,history,page['extract'] if page else ''):
                    output = True
                    yield 'delta', {'text':token}
                if not output:
                    raise ProviderError('Groq returned an empty answer.')
                yield 'meta', {'source':f'Groq · {self.model}'+(' · Wikipedia context' if page else ' · not web-verified'),'sources':source_list}
                return
            except ProviderError as e:
                yield 'notice', {'text':str(e)}
                if output:
                    yield 'delta', {'text':'\n\n[Response interrupted. This answer may be incomplete.]'}
                    yield 'meta', {'source':'Interrupted Groq response','sources':source_list}
                    return
                if not page:
                    try:
                        page = self.wikipedia.lookup(question)
                    except Exception:
                        yield 'notice', {'text':'Wikipedia fallback is also unavailable.'}
        if page:
            yield 'delta', {'text':f"Wikipedia excerpt — {page['title']}\n\n{page['extract']}\n\nThis is an encyclopedia match, not a tailored or live-verified answer."}
            yield 'meta', {'source':'Wikipedia excerpt','sources':[{'title':page['title'],'url':page['url']}]}
        else:
            yield 'delta', {'text':'I could not retrieve a reliable answer. Check your connection, try a more specific question, or configure a new Groq key in .env.'}
            yield 'meta', {'source':'No answer retrieved','sources':[]}
