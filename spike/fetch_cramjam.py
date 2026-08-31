import urllib.request
import re
import zipfile
import os
import sys

# cramjam simple index
url = 'https://pypi.org/simple/cramjam/'
req = urllib.request.Request(url, headers={'User-Agent': 'playerlab'})
html = urllib.request.urlopen(req).read().decode()
links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
wheels = [(h, n) for h, n in links if n.endswith('.whl') and 'cp313' in n and 'win_amd64' in n]
if not wheels:
    wheels = [(h, n) for h, n in links if n.endswith('.whl') and ('abi3' in n or 'py3' in n) and 'win_amd64' in n]
print('candidate wheels:', len(wheels))
for h, n in wheels[:6]:
    print(n)
if wheels:
    href, name = wheels[0]
    local = '.tmp-pip/' + name
    print('downloading', href)
    urllib.request.urlretrieve(href, local)
    with zipfile.ZipFile(local) as z:
        z.extractall('.tmp-pip/cramjam-extract')
    print('extracted:', os.listdir('.tmp-pip/cramjam-extract'))
