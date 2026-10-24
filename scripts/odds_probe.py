#!/usr/bin/env python3
"""One-off probe of the SportsGameOdds feed: pull today's NBA events and save a trimmed sample."""
import json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
KEY=os.environ.get("ODDS_API_KEY","")
if not KEY: sys.exit("ODDS_API_KEY not set")
BASE="https://api.sportsgameodds.com/v2"
now=datetime.now(timezone.utc)
q={"leagueID":"NBA","startsAfter":(now-timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),"startsBefore":(now+timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%SZ"),"limit":"50"}
url=BASE+"/events/?"+urllib.parse.urlencode(q)
req=urllib.request.Request(url,headers={"x-api-key":KEY,"User-Agent":"meats-nba-calcutta/1.0"})
try:
    with urllib.request.urlopen(req,timeout=60) as r:
        body=r.read().decode(); print("status",r.status,"bytes",len(body)); d=json.loads(body)
except urllib.error.HTTPError as e:
    print("HTTP",e.code,e.read().decode()[:500]); sys.exit(1)
evs=d.get("data",[]); print("events",len(evs),"nextCursor",bool(d.get("nextCursor")))
out=Path("data/odds_sample.json")
sample=[]
for ev in evs[:3]:
    odds=ev.get("odds") or {}
    keys=list(odds.keys())
    books=set()
    for v in odds.values():
        books.update((v.get("byBookmaker") or {}).keys())
    sample.append({"eventID":ev.get("eventID"),"status":ev.get("status"),"teams":ev.get("teams"),"oddCount":len(odds),"oddIDs_first40":keys[:40],
      "books":sorted(books),"example_odds":{k:odds[k] for k in keys[:6]},"players_sample":dict(list((ev.get("players") or {}).items())[:3]),"results":ev.get("results")})
out.write_text(json.dumps(sample,indent=1)[:400000])
print("wrote",out)
