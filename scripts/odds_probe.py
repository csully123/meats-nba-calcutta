#!/usr/bin/env python3
import json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
KEY=os.environ["ODDS_API_KEY"]
now=datetime.now(timezone.utc)
q={"leagueID":"NBA","startsAfter":now.strftime("%Y-%m-%dT%H:%M:%SZ"),"startsBefore":(now+timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),"limit":"1","includeAltLines":"true","bookmakerID":"fanduel"}
req=urllib.request.Request("https://api.sportsgameodds.com/v2/events/?"+urllib.parse.urlencode(q),headers={"x-api-key":KEY})
d=json.load(urllib.request.urlopen(req,timeout=90))
ev=d["data"][0]; odds=ev["odds"]
out={"eventID":ev["eventID"],"teams":{k:v["names"]["short"] for k,v in ev["teams"].items()},"oddCount":len(odds)}
samples={}
for k,v in odds.items():
    if k.startswith("points-home-game-sp-") or k.startswith("points-all-game-ou-over") or ("-game-ou-over" in k and "_NBA" in k and k.startswith("points-")):
        samples[k]=v
        if len(samples)>=4: break
out["samples"]=samples
# also check for any keys that look like alt markers
out["keys_with_alt"]=[k for k in odds if "alt" in k.lower()][:20]
anyv=next(iter(odds.values())); out["entry_keys"]=list(anyv.keys()); out["byBookmaker_entry_keys"]=list(next(iter((anyv.get("byBookmaker") or {"x":{}}).values())).keys())
Path("data/odds_alt_sample.json").write_text(json.dumps(out,indent=1)[:300000])
print("ok",out["oddCount"])
