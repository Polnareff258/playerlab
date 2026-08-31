import urllib.request
import re
import sys
url = 'https://pypi.org/simple/python-snappy/'
req = urllib.request.Request(url, headers={'User-Agent': 'playerlab'})
html = urllib.request.urlopen(req).read().decode()
links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
wheels = [(h, n) for h, n in links if n.endswith('.whl')]
print('total wheels:', len(wheels))
# python 3.13 win amd64 (cp313 / abi3 / py3)
targets = [n for h, n in wheels if 'cp313' in n or 'py3-none' in n or 'abi3' in n]
for t in targets[:20]:
    print(t)
