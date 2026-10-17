import csv, json, math, os, time
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE="https://fapi.binance.com"
OUT=Path("data"); OUT.mkdir(exist_ok=True)
STAMP=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
S=requests.Session(); S.headers.update({"User-Agent":"research-only-trigger-checker/1.0"})
FEE=float(os.getenv("FEE_PER_SIDE","0.0005"))
SLIP=float(os.getenv("SLIPPAGE_PER_SIDE","0.0002"))
MIN_RR=2.0

def get(path, params=None):
    last=None
    for attempt in range(3):
        try:
            r=S.get(BASE+path,params=params,timeout=20); r.raise_for_status(); return r.json()
        except Exception as e:
            last=e; time.sleep(attempt+1)
    raise RuntimeError(f"{path}: {last}")

def num(v, default=float("nan")):
    try: return float(v)
    except (TypeError,ValueError): return default

def candles(symbol, interval, limit=100):
    raw=get("/fapi/v1/klines",{"symbol":symbol,"interval":interval,"limit":limit})
    now=int(datetime.now(timezone.utc).timestamp()*1000); out=[]
    for k in raw:
        if int(k[6]) >= now: continue
        out.append({"open_time":int(k[0]),"close_time":int(k[6]),"open":num(k[1]),"high":num(k[2]),"low":num(k[3]),"close":num(k[4]),"volume":num(k[5])})
    return out

def ema(vals, span):
    a=2/(span+1); out=[]; cur=None
    for v in vals: cur=v if cur is None else a*v+(1-a)*cur; out.append(cur)
    return out[-1] if out else float("nan")

def atr(rows, period=14):
    tr=[]
    for i,r in enumerate(rows):
        pc=rows[i-1]["close"] if i else r["close"]
        tr.append(max(r["high"]-r["low"],abs(r["high"]-pc),abs(r["low"]-pc)))
    return sum(tr[-period:])/min(period,len(tr)) if tr else float("nan")

def rsi(vals, p=14):
    ds=[vals[i]-vals[i-1] for i in range(1,len(vals))]
    gains=[max(d,0) for d in ds][-p:]; losses=[max(-d,0) for d in ds][-p:]
    if not losses: return float("nan")
    ag=sum(gains)/len(gains); al=sum(losses)/len(losses)
    return 100 if al==0 else 100-100/(1+ag/al)

def universe():
    info=get("/fapi/v1/exchangeInfo"); tickers={x["symbol"]:x for x in get("/fapi/v1/ticker/24hr")}
    rows=[]
    for x in info.get("symbols",[]):
        if x.get("status")=="TRADING" and x.get("contractType")=="PERPETUAL" and x.get("quoteAsset")=="USDT" and x["symbol"] in tickers:
            q=num(tickers[x["symbol"]].get("quoteVolume"),0)
            if q>0: rows.append({"symbol":x["symbol"],"quote_volume_24h":q})
    return sorted(rows,key=lambda x:x["quote_volume_24h"],reverse=True)[:50]

def analyze(item):
    sym=item["symbol"]; m15=candles(sym,"15m"); h1=candles(sym,"1h"); h4=candles(sym,"4h")
    if min(len(m15),len(h1),len(h4))<55: raise ValueError("not enough closed candles")
    p=get("/fapi/v1/premiumIndex",{"symbol":sym}); oi=get("/fapi/v1/openInterest",{"symbol":sym})
    oi_ch=float("nan")
    try:
        hist=get("/futures/data/openInterestHist",{"symbol":sym,"period":"1h","limit":2})
        if len(hist)>=2:
            a=num(hist[-2].get("sumOpenInterestValue")); b=num(hist[-1].get("sumOpenInterestValue"))
            if a>0: oi_ch=(b/a-1)*100
    except Exception: pass
    c1=[x["close"] for x in h1]; c4=[x["close"] for x in h4]
    r15=m15[-1]; r1=h1[-1]; r4=h4[-1]; price=r1["close"]
    e20_1,e50_1=ema(c1,20),ema(c1,50); e20_4,e50_4=ema(c4,20),ema(c4,50)
    a1=atr(h1[-30:]); rs=rsi(c1); hi=max(x["high"] for x in h1[-21:-1]); lo=min(x["low"] for x in h1[-21:-1])
    avgvol=sum(x["volume"] for x in h1[-21:-1])/20; vr=r1["volume"]/avgvol if avgvol else float("nan")
    funding=num(p.get("lastFundingRate")); mark=num(p.get("markPrice"))
    ls=ss=0; lr=[]; sr=[]
    if e20_4>e50_4: ls+=2; lr.append("4h EMA20>EMA50")
    elif e20_4<e50_4: ss+=2; sr.append("4h EMA20<EMA50")
    if e20_1>e50_1: ls+=2; lr.append("1h EMA20>EMA50")
    elif e20_1<e50_1: ss+=2; sr.append("1h EMA20<EMA50")
    if price>e20_1: ls+=1; lr.append("price above 1h EMA20")
    elif price<e20_1: ss+=1; sr.append("price below 1h EMA20")
    if price>hi: ls+=2; lr.append("1h close above prior 20h high")
    if price<lo: ss+=2; sr.append("1h close below prior 20h low")
    if math.isfinite(vr) and vr>=1.3:
        if price>e20_1: ls+=1; lr.append("volume >=1.3x average")
        elif price<e20_1: ss+=1; sr.append("volume >=1.3x average")
    if math.isfinite(rs):
        if 52<=rs<=72: ls+=1; lr.append("RSI bullish range")
        elif 28<=rs<=48: ss+=1; sr.append("RSI bearish range")
    if math.isfinite(funding):
        if funding>0.001: ls-=1; lr.append("positive-funding caution")
        if funding<-0.001: ss-=1; sr.append("negative-funding caution")
    stopd=1.5*a1; rows=[]; costrate=2*(FEE+SLIP)
    for side,score,reasons,trigger in [("LONG",ls,lr,hi),("SHORT",ss,sr,lo)]:
        if score<6 or not math.isfinite(stopd) or stopd<=0: continue
        if side=="LONG":
            stop=trigger-stopd; t1=trigger+2*stopd; t2=trigger+3*stopd
            fired=r15["close"]>trigger; extended=r15["close"]>trigger+0.5*stopd
        else:
            stop=trigger+stopd; t1=trigger-2*stopd; t2=trigger-3*stopd
            fired=r15["close"]<trigger; extended=r15["close"]<trigger-0.5*stopd
        netrr=max(0,abs(t1-trigger)-trigger*costrate)/(abs(trigger-stop)+trigger*costrate)
        status="WATCHLIST CANDIDATE"
        if fired and not extended and netrr>=MIN_RR: status="TRIGGERED (PAPER ONLY)"
        elif extended: status="EXTENDED — DO NOT CHASE"
        rows.append({"symbol":sym,"side":side,"score":score,"status":status,"entry_trigger":trigger,"stop":stop,"t1":t1,"t2":t2,"gross_rr_t1":abs(t1-trigger)/abs(trigger-stop),"estimated_net_rr_t1":netrr,"close_15m":r15["close"],"close_1h":price,"mark_price":mark,"funding_rate":funding,"open_interest":num(oi.get("openInterest")),"oi_value_change_1h_pct":oi_ch,"rsi_1h":rs,"volume_ratio_1h":vr,"quote_volume_24h_usdt":item["quote_volume_24h"],"last_closed_15m_utc":datetime.fromtimestamp(r15["close_time"]/1000,timezone.utc).isoformat(),"last_closed_1h_utc":datetime.fromtimestamp(r1["close_time"]/1000,timezone.utc).isoformat(),"last_closed_4h_utc":datetime.fromtimestamp(r4["close_time"]/1000,timezone.utc).isoformat(),"reasons":"; ".join(reasons)})
    return rows

def main():
    now=datetime.now(timezone.utc); print("Research scan UTC:",now.isoformat()); print("Source: Binance public USDⓈ-M Futures REST API; no credentials or orders.")
    uni=universe(); print("Top eligible contracts selected:",len(uni)); results=[]; errors=[]
    for i,item in enumerate(uni,1):
        try: results.extend(analyze(item))
        except Exception as e: errors.append({"symbol":item["symbol"],"error":str(e)[:200]})
        if i%5==0: print(f"Processed {i}/{len(uni)}")
        time.sleep(.08)
    results.sort(key=lambda x:x["score"],reverse=True)
    report={"scan_time_utc":now.isoformat(),"source":"Binance public USDⓈ-M Futures REST API","eligible_top50_count":len(uni),"symbols_with_candidates":len(set(x["symbol"] for x in results)),"errors":errors,"portfolio_risk_evaluated":False,"live_orders_enabled":False,"limitations":"Heuristic not validated; funding holding cost and portfolio correlation not modeled; fees/slippage illustrative; OI history may be unavailable.","candidates":results}
    OUT.mkdir(exist_ok=True); (OUT/f"scan_{STAMP}.json").write_text(json.dumps(report,indent=2,allow_nan=True))
    fields=sorted({k for x in results for k in x if k!="reasons"})
    with (OUT/f"scan_{STAMP}.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for x in results: w.writerow({k:v for k,v in x.items() if k!="reasons"})
    print(f"Results with candidates from {len(set(x['symbol'] for x in results))}/{len(uni)} symbols; scan errors: {len(errors)}")
    for side in ("LONG","SHORT"):
        subset=[x for x in results if x["side"]==side]
        print("\\nTOP",side)
        if not subset: print("No qualifying candidates.")
        for x in subset[:5]:
            print(f"{x['symbol']} score={x['score']} {x['status']} trigger={x['entry_trigger']:.8g} stop={x['stop']:.8g} T1={x['t1']:.8g} T2={x['t2']:.8g} netRR~{x['estimated_net_rr_t1']:.2f}")
    print("Portfolio risk evaluated: NO. No live orders placed. See data/ for report.")
if __name__=="__main__": main()
