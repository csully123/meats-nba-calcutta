#!/usr/bin/env python3
import json, os, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
KEY=os.environ["ODDS_API_KEY"]
now=datetime.now(timezone.utc)
q={"leagueID":"NBA","startsAfter":now.strftime("%Y-%m-%dT%H:%M:%SZ"),"startsBefore":(now+timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),"limit":"1","includeAltLines":"true"}
req=urllib.request.Request("https://api.sportsgameodds.com/v2/events/?"+urllib.parse.urlencode(q),headers={"x-api-key":KEY})
try:
    raw=urllib.request.urlopen(req,timeout=90).read().decode()
except urllib.error.HTTPError as e:
    raw=json.dumps({"http_error":e.code,"body":e.read().decode()[:2000]})
Path("data/odds_alt_sample.json").write_text(raw[:1500000])
print("saved",len(raw),"bytes")
