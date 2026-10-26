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
    const mult=(w.boost&&Number(w.boost.mult))||1; // a boost token multiplies the profit, never the stake
    const profit=Math.round(w.stake*(dec-1)*mult); // whole points: payouts round to the nearest point
    return {status:'win',net:profit,payout:w.stake+profit};
  };
  E.boostedProfit=function(stake,legs,mult){return Math.round(stake*(E.parlayDecimal(legs)-1)*(mult||1));};

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
    for(const a of (cfg.adjustments||[]))if(a.player===player&&a.at&&a.at<=new Date().toISOString())timeline.push({t:a.at,kind:'adjust',a});
    timeline.sort((a,b)=>a.t<b.t?-1:a.t>b.t?1:(a.kind==='place'?-1:1));
    let wagered=0;const byWeek={};
    for(const ev of timeline){
      if(ev.kind==='adjust'){stack+=Number(ev.a.points)||0;}
      else if(ev.kind==='place'){stack-=ev.w.stake;pending+=ev.w.stake;wagered+=ev.w.stake;const wk=E.weekKey(ev.w.placedAt);byWeek[wk]=(byWeek[wk]||0)+ev.w.stake;}
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
  E.FOUL_OUT=6; // six busts and you have fouled out: out of the competition entirely
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
  // Pairs that a real book prices as one bet but our multiplication would overpay: first-half and full-game lines on the
  // same quantity, and a player's combined stat with one of its parts. 'related' legs can be singles, never one parlay.
  E.COMBO_PARTS={'points+rebounds+assists':['points','rebounds','assists'],'points+rebounds':['points','rebounds'],'points+assists':['points','assists'],
    'rebounds+assists':['rebounds','assists'],'blocks+steals':['blocks','steals'],'doubleDouble':['points','rebounds','assists'],'tripleDouble':['points','rebounds','assists']};
  E.related=function(a,b){const pa=a.period||'game',pb=b.period||'game';
    if(!a.player&&!b.player&&pa!==pb){const team=l=>l.betType==='ml'||l.betType==='sp';const total=l=>l.betType==='ou';
      if(team(a)&&team(b))return 'first-half and full-game lines on the same game';
      if(total(a)&&total(b))return 'first-half and full-game totals';}
    if(a.player&&b.player&&a.player===b.player&&a.stat!==b.stat){const A=E.COMBO_PARTS[a.stat]||[],B=E.COMBO_PARTS[b.stat]||[];
      if(A.includes(b.stat)||B.includes(a.stat)||A.some(x=>B.includes(x)))return 'a combined stat and one of its parts for the same player';}
    return null;};
  E.conflict=function(a,b){const x=E.legConstraint(a),y=E.legConstraint(b);
    if(x&&y&&x.v===y.v){if(x.dir===y.dir)return 'overlap';const gt=x.dir==='>'?x:y,lt=x.dir==='<'?x:y;return gt.at>=lt.at?'impossible':null;}
    return E.related(a,b)?'related':null;};

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
      for(let i=0;i<w.legs.length&&!errs.length;i++)for(let j=i+1;j<w.legs.length;j++){const c=E.conflict(w.legs[i],w.legs[j]);if(c){const a=w.legs[i].short||'one leg',b=w.legs[j].short||'another';errs.push(c==='impossible'?`${a} and ${b} cannot both win.`:c==='related'?`${a} and ${b} are too closely related to parlay (${E.related(w.legs[i],w.legs[j])}).`:`${a} and ${b} overlap (one already covers the other), so they cannot be parlayed.`);break;}}}
    return errs;
  };

  // ---------- boost tokens ----------
  // Every player gets the same tokens. Each is good for one bet inside its window and is spent by any open, won or
  // lost bet carrying it; a bet that pushes or voids hands it back. Ids are stable so a wager can carry them.
  E.ROUND_NAMES={r1:'first round',r2:'second round',cf:'conference finals',finals:'NBA Finals'};
  E.seriesKey=function(a,b){return [a,b].sort().join('-');};
  // Tokens usable on game g ({start, stage, series}) by this player, before removing the ones already spent.
  E.tokensForGame=function(g,cfg,player){const T=(cfg&&cfg.tokens)||{};const out=[];const prizes=(cfg&&cfg.prizes)||{};
    const wk=E.weekKey(g.start);if(wk&&T.week)out.push({id:'week:'+wk,mult:T.week,label:`${T.week}x weekly`,why:'this week'});
    if(g.stage==='cupfinal'&&T.cupFinal)out.push({id:'cupfinal',mult:T.cupFinal,label:`${T.cupFinal}x Cup final`,why:'NBA Cup championship'});
    if((g.stage==='r1'||g.stage==='r2'||g.stage==='cf')&&g.series&&T[g.stage])out.push({id:g.stage+':'+g.series,mult:T[g.stage],label:`${T[g.stage]}x series`,why:`${E.ROUND_NAMES[g.stage]} series`});
    if(g.stage==='finals'&&T.finals){out.push({id:'finals',mult:T.finals,label:`${T.finals}x Finals`,why:'NBA Finals'});
      if(prizes.first===player&&prizes.firstMult)out.push({id:'prize:first',mult:prizes.firstMult,label:`${prizes.firstMult}x Finals (season prize)`,why:'regular-season winner'});}
    if(g.stage==='r2'&&prizes.second===player&&prizes.secondMult)out.push({id:'prize:second',mult:prizes.secondMult,label:`${prizes.secondMult}x second round (season prize)`,why:'regular-season runner-up'});
    if(T.mega)out.push({id:'mega',mult:T.mega,label:`${T.mega}x Mega Bonus`,why:'once a season',mega:true});
    return out;};
  E.tokenSpentBy=function(w){return !!(w.boost&&w.boost.id)&&w.status!=='push'&&w.status!=='void';};
  E.spentTokenIds=function(player,wagers){const s=new Set();for(const w of wagers)if(w.player===player&&E.tokenSpentBy(w))s.add(w.boost.id);return s;};
  E.availableTokens=function(g,cfg,player,wagers){const spent=E.spentTokenIds(player,wagers);return E.tokensForGame(g,cfg,player).filter(t=>!spent.has(t.id));};
  // Can this token be attached to a bet on this game? (window check at placement and again when grading nothing; grading trusts the stored mult)
  E.tokenAllowed=function(tokenId,g,cfg,player,wagers){return E.availableTokens(g,cfg,player,wagers).some(t=>t.id===tokenId);};

  E.weekKey=function(iso){if(!iso)return '';const d=new Date(iso);const et=new Date(d.toLocaleString('en-US',{timeZone:'America/New_York'}));const day=(et.getDay()+6)%7;et.setDate(et.getDate()-day);return et.getFullYear()+'-'+String(et.getMonth()+1).padStart(2,'0')+'-'+String(et.getDate()).padStart(2,'0');};

  if(typeof module!=='undefined'&&module.exports)module.exports=E;else root.BookEngine=E;
})(typeof window!=='undefined'?window:globalThis);
