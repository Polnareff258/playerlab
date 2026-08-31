import urllib.request
import re
import zipfile
import os
import sys

url = 'https://pypi.org/simple/python-snappy/'
req = urllib.request.Request(url, headers={'User-Agent': 'playerlab'})
html = urllib.request.urlopen(req).read().decode()
links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
whl = next((h for h, n in links if n == 'python_snappy-0.7.3-py3-none-any.whl'), None)
if not whl:
    print('wheel link not found')
    sys.exit(1)
print('downloading', whl)
local = '.tmp-pip/python_snappy-0.7.3-py3-none-any.whl'
urllib.request.urlretrieve(whl, local)
with zipfile.ZipFile(local) as z:
    z.extractall('.tmp-pip/snappy-extract')
print('extracted:', os.listdir('.tmp-pip/snappy-extract'))
