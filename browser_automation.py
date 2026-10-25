"""Allowlisted browser actions, executed by the user's browser, never by a shell."""
import re
from urllib.parse import urlencode

SITES = {
 'youtube': ('YouTube', 'https://www.youtube.com', 'https://www.youtube.com/results', 'search_query'),
 'google': ('Google', 'https://www.google.com', 'https://www.google.com/search', 'q'),
 'wikipedia': ('Wikipedia', 'https://en.wikipedia.org', 'https://en.wikipedia.org/w/index.php', 'search'),
 'github': ('GitHub', 'https://github.com', 'https://github.com/search', 'q'),
 'amazon': ('Amazon', 'https://www.amazon.in', 'https://www.amazon.in/s', 'k'),
 'gmail': ('Gmail', 'https://mail.google.com', None, None),
 'netflix': ('Netflix', 'https://www.netflix.com', None, None),
 'chatgpt': ('ChatGPT', 'https://chatgpt.com', None, None),
 'chat gpt': ('ChatGPT', 'https://chatgpt.com', None, None),
 'openai': ('ChatGPT', 'https://chatgpt.com', None, None),
 'claude': ('Claude', 'https://claude.ai', None, None),
 'gemini': ('Gemini', 'https://gemini.google.com', None, None),
 'whatsapp': ('WhatsApp', 'https://web.whatsapp.com', None, None),
 'spotify': ('Spotify', 'https://open.spotify.com', None, None),
 'twitter': ('Twitter / X', 'https://x.com', None, None),
 'x': ('Twitter / X', 'https://x.com', None, None),
}

class BrowserAutomation:
    def parse_command(self, command):
        command = command.strip().rstrip('.!?')
        match = re.fullmatch(r'open\s+(?:the\s+|a\s+|an\s+)?(?:website\s+|site\s+|webpage\s+|app\s+named\s+|app\s+called\s+|application\s+named\s+|app\s+|application\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+in\s+(?:chrome|firefox|edge|browser))?(?:\s+and\s+search\s+(?:for\s+)?(.+))?', command, re.I)
        if match:
            site_candidate = match[1].strip().lower()
            site_candidate = re.sub(r'^(?:named|called)\s+', '', site_candidate).strip()
            if site_candidate in SITES or site_candidate.replace(' ', '') in SITES:
                return (site_candidate if site_candidate in SITES else site_candidate.replace(' ', '')), match[2]
            return site_candidate, match[2]
        match = re.fullmatch(r'search\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(\w+)', command, re.I)
        if match:
            return match[2].lower(), match[1]
        match = re.fullmatch(r'search\s+(youtube|google|wikipedia|github|amazon)\s+for\s+(.+)', command, re.I)
        if match:
            return match[1].lower(), match[2]
        return None

    def execute_command(self, command):
        parsed = self.parse_command(command)
        if not parsed:
            return None
        site, query = parsed
        if site not in SITES:
            return {'text':'That website is not enabled. Try YouTube, Google, Wikipedia, GitHub, Amazon, Gmail or Netflix.', 'source':'Browser actions'}
        label, home, endpoint, parameter = SITES[site]
        if query and not endpoint:
            return {'text':f'{label} search is not supported. Open the website instead.', 'source':'Browser actions'}
        url = endpoint+'?'+urlencode({parameter:query.strip()}) if query else home
        text = f'{label} results for “{query.strip()}” are ready.' if query else f'{label} is ready to open.'
        text += ' Use the results button if your browser blocks the new tab.'
        return {'text':text,'source':'Browser actions','action':{'url':url,'label':f'Open {label} results' if query else f'Open {label}'}}
