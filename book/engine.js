// Meats NBA Calcutta sportsbook engine. Pure functions, no DOM, so they can be tested and reused by the grader.
(function(root){
  const E={};

  // American odds helpers
  E.decimal=function(american){const a=Number(american);if(!isFinite(a)||a===0)return null;return a>0?1+a/100:1+100/Math.abs(a);};
  E.american=function(decimal){const d=Number(decimal);if(!isFinite(d)||d<=1)return null;const p=d-1;return p>=1?Math.round(p*100):-Math.round(100/p);};
  E.fmtAmerican=function(a){if(a==null)return '';return (a>0?'+':'')+a;};
  E.parlayDecimal=function(legs){return legs.reduce((acc,l)=>acc*(E.decimal(l.odds)||1),1);};

  // Payout for a settled wager: returns net change to the stack (profit on a win, -stake on a loss, 0 on a push/void).
  // A push leg in a parlay drops out (odds 1.0); a lost leg loses the slip.
  E.settle=function(w,legResults){ // legResults: array aligned with w.legs, each 'win'|'loss'|'push'|'void'|null
    if(legResults.some(r=>r==null))return {status:'open',net:0};
    if(legResults.some(r=>r==='loss'))return {status:'loss',net:-w.stake};
    let dec=1,live=0;
    w.legs.forEach((l,i)=>{if(legResults[i]==='win'){dec*=E.decimal(l.odds)||1;live++;}});
    if(live===0)return {status:'push',net:0};
    const profit=Math.round(w.stake*(dec-1)); // whole points: payouts round to the nearest point
    return {status:'win',net:profit,payout:w.stake+profit};
  };

  // Bankroll replay. wagers: array of {player, stake, placedAt, settled:{status,net}|null}. Config: start, reload.
  // Returns per player: stack, busts, totalWagered, byWeek wagered, history of stack after each settlement.
  E.bankroll=function(player,wagers,cfg){
    const start=cfg.start||100,reload=cfg.reload||start;
    const mine=wagers.filter(w=>w.player===player).slice().sort((a,b)=>(a.placedAt||'')<(b.placedAt||'')?-1:1);
    let stack=start,busts=0;const events=[];let pending=0;
    // Stakes come off the stack when placed; winnings return at settlement. Replay in placement order, applying settlements
    // in settlement order to keep "stack at placement" honest.
    const timeline=[];
    for(const w of mine){timeline.push({t:w.placedAt||'',kind:'place',w});if(w.settled&&w.settledAt)timeline.push({t:w.settledAt,kind:'settle',w});}
    timeline.sort((a,b)=>a.t<b.t?-1:a.t>b.t?1:(a.kind==='place'?-1:1));
    let wagered=0;const byWeek={};
    for(const ev of timeline){
      if(ev.kind==='place'){stack-=ev.w.stake;pending+=ev.w.stake;wagered+=ev.w.stake;const wk=E.weekKey(ev.w.placedAt);byWeek[wk]=(byWeek[wk]||0)+ev.w.stake;}
      else{pending-=ev.w.stake;const s=ev.w.settled;if(s.status==='win')stack+=ev.w.stake+s.net;else if(s.status==='push'||s.status==='void')stack+=ev.w.stake;
        if(stack<=0.005&&pending<=0.005){busts++;events.push({t:ev.t,bust:busts});stack=reload;}}
      events.push({t:ev.t,stack:Math.round(stack*100)/100});
    }
    return {stack:Math.round(stack*100)/100,pending:Math.round(pending*100)/100,busts,wagered:Math.round(wagered*100)/100,byWeek,events};
  };

  // End-of-season figure after the proportional bust penalty: first bust x2/3, second x1/2, third x1/3, nth x 1/(n+1)... using factor 2/(n+2).
  // Bust penalty: a cumulative percentage of the final stack (10%, 25%, 45%, 70%, then 90% for anything beyond),
  // with a floor of 20 points per bust so a deliberate bust for the reload is never a good trade.
  E.PENALTY_PCT=[0,0.10,0.25,0.45,0.70,0.90];
  E.FOUL_OUT=6; // six busts and you have fouled out: last place at the auction, behind everyone still standing
  E.PENALTY_FLOOR=20;
  E.penaltyPct=function(busts){busts=Math.max(0,Math.floor(busts||0));return E.PENALTY_PCT[Math.min(busts,E.PENALTY_PCT.length-1)];};
  E.penaltyAmount=function(stack,busts){busts=Math.max(0,Math.floor(busts||0));if(!busts)return 0;return Math.max(stack*E.penaltyPct(busts),E.PENALTY_FLOOR*busts);};
  E.penaltyFactor=function(busts){return 1-E.penaltyPct(busts);};
  E.fouledOut=function(busts){return (busts||0)>=E.FOUL_OUT;}; // kept for display; the floor can make the real cut larger
  E.finalTotal=function(stack,busts){return Math.max(0,Math.round((stack-E.penaltyAmount(stack,busts))*100)/100);};

  // What a leg says about the game, as a one-sided bound on one quantity: {v, dir:'>'|'<', at}.
  // Two legs on the same quantity in opposite directions with no room between them cannot both win (SAS -15.5 with DAL ML);
  // two in the same direction overlap, one already implies the other (SAS -15.5 with SAS ML), which a parlay must not stack.
  E.legConstraint=function(l){const line=Number(l.line);const per=l.period||'game';
    if(l.player){if(l.betType==='ou'&&isFinite(line))return {v:'p:'+l.player+':'+l.stat,dir:l.side==='under'?'<':'>',at:line};
      if(l.betType==='yn')return {v:'p:'+l.player+':'+l.stat,dir:l.side==='no'?'<':'>',at:0.5};return null;}
    if(l.betType==='ml'&&(l.entity==='home'||l.entity==='away'))return {v:'margin:'+per,dir:l.entity==='home'?'>':'<',at:0};
    if(l.betType==='sp'&&isFinite(line)&&(l.entity==='home'||l.entity==='away'))return l.entity==='home'?{v:'margin:'+per,dir:'>',at:-line}:{v:'margin:'+per,dir:'<',at:line};
    if(l.betType==='ou'&&isFinite(line))return {v:'total:'+per,dir:l.side==='under'?'<':'>',at:line};
    return null;};
  E.conflict=function(a,b){const x=E.legConstraint(a),y=E.legConstraint(b);if(!x||!y||x.v!==y.v)return null;
    if(x.dir===y.dir)return 'overlap';const gt=x.dir==='>'?x:y,lt=x.dir==='<'?x:y;return gt.at>=lt.at?'impossible':null;};

  // Biggest single bet allowed: 25% of the available stack, rounded down to a whole point. Once the whole bankroll
  // (available plus open bets) is at or under ALL_IN_AT, the cap lifts and you may bet everything you have left.
  E.ALL_IN_AT=20;
  E.allIn=function(state){return (state.stack||0)+(state.pending||0)<=E.ALL_IN_AT+0.0001;};
  E.maxBet=function(state,cfg){const maxFrac=(cfg&&cfg.maxBetFraction)||0.25;const stack=Math.max(0,state.stack||0);
    return E.allIn(state)?Math.floor(stack+0.0001):Math.floor(stack*maxFrac+0.0001);};

  // Rules checks for a new wager
  E.validate=function(w,state,cfg){
    const errs=[];const maxFrac=(cfg&&cfg.maxBetFraction)||0.25;
    if(!(w.stake>0))errs.push('Enter a stake.');
    else if(!Number.isInteger(w.stake))errs.push('Stakes are whole points.');
    if(w.stake>state.stack+0.0001)errs.push(`You only have ${state.stack} points available.`);
    const cap=E.maxBet(state,cfg);
    if(w.stake>cap+0.0001)errs.push(E.allIn(state)?`You can bet up to your whole ${cap} right now.`:`Max bet is ${Math.round(maxFrac*100)}% of your stack (${cap} right now).`);
    if(!w.legs||!w.legs.length)errs.push('Add at least one selection.');
    if(w.legs&&new Set(w.legs.map(l=>l.eventID)).size>1)errs.push('All selections must be from the same game.');
    if(w.legs&&w.legs.some(l=>l.started))errs.push('One of these games has already started.');
    if(w.legs&&w.legs.length>1){const ids=w.legs.map(l=>l.oddID);if(new Set(ids).size!==ids.length)errs.push('Duplicate selection.');
      const opp=w.legs.some(l=>{const o=l.opposingOddID||l.opposing;return !!o&&w.legs.some(m=>m.oddID===o);});if(opp)errs.push('You cannot take both sides of the same market.');
      for(let i=0;i<w.legs.length&&!errs.length;i++)for(let j=i+1;j<w.legs.length;j++){const c=E.conflict(w.legs[i],w.legs[j]);if(c){const a=w.legs[i].short||'one leg',b=w.legs[j].short||'another';errs.push(c==='impossible'?`${a} and ${b} cannot both win.`:`${a} and ${b} overlap (one already covers the other), so they cannot be parlayed.`);break;}}}
    return errs;
  };

  E.weekKey=function(iso){if(!iso)return '';const d=new Date(iso);const et=new Date(d.toLocaleString('en-US',{timeZone:'America/New_York'}));const day=(et.getDay()+6)%7;et.setDate(et.getDate()-day);return et.getFullYear()+'-'+String(et.getMonth()+1).padStart(2,'0')+'-'+String(et.getDate()).padStart(2,'0');};

  if(typeof module!=='undefined'&&module.exports)module.exports=E;else root.BookEngine=E;
})(typeof window!=='undefined'?window:globalThis);
