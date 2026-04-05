"""
=============================================================================
VN STOCK SCANNER v3.1 — Render 24/7 Edition
=============================================================================
TÍNH NĂNG MỚI (v3.1):
  ✅ Flask Webhook — Telegram bot phản hồi tức thì khi nhận mã CP
  ✅ On-demand Analysis — Chat mã lên bot → nhận phân tích chi tiết ngay
  ✅ Scheduled Daily Scan — Quét toàn bộ watchlist lúc 8:15 SA (giờ VN)
  ✅ Health-check endpoint — Render keep-alive
  ✅ Thread-safe — phân tích chạy nền, không block webhook
  ✅ Lệnh bot: /scan /status /help + gõ mã CP bất kỳ
=============================================================================
CÁCH DEPLOY TRÊN RENDER:
  1. Tạo Web Service trên Render (không phải Worker)
  2. Build Command : pip install -r requirements.txt
  3. Start Command : gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120
  4. Environment Variables:
       TELEGRAM_BOT_TOKEN = <token>
       TELEGRAM_CHAT_ID   = <chat_id>   (cho daily scan)
       VNSTOCK_API_KEY    = <key hoặc bỏ trống>
       WEBHOOK_URL        = https://<your-app>.onrender.com
  5. Sau khi deploy xong → gọi: GET /set_webhook để đăng ký webhook
=============================================================================
"""
from __future__ import annotations

import os
import re
import time
import logging
import threading
import traceback
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta as ta
import requests
import pytz
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from vnstock import Vnstock

# ===========================================================================
# LOGGING
# ===========================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ===========================================================================
# CẤU HÌNH HỆ THỐNG
# ===========================================================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')    # Chat nhận daily scan
VNSTOCK_API_KEY    = os.getenv('VNSTOCK_API_KEY', '')
WEBHOOK_URL        = os.getenv('WEBHOOK_URL', '')          # https://yourapp.onrender.com

PORT               = int(os.getenv('PORT', 10000))
VN_TZ              = pytz.timezone('Asia/Ho_Chi_Minh')

DEBUG_MODE         = os.getenv('DEBUG_MODE', 'false').lower() == 'true'

# Tham số phân tích
MIN_RR_RATIO       = 2.5
MAX_SL_PCT         = 0.05
MIN_TP_PCT         = 0.10
MIN_SMC_SCORE      = 3
TOP_N_SIGNALS      = 10
TOP_N_APPROACHING  = 5

RS_LOOKBACK        = 20
RS_MIN_BEAR        = 1.05

OTE_LOW            = 0.618
OTE_HIGH           = 0.786
FIB_LEVELS         = [0.236, 0.382, 0.500, 0.618, 0.786]
TP_EXT_127         = 1.272
TP_EXT_162         = 1.618

MCDX_THRESH_1      = 55
MCDX_THRESH_2      = 70

# Semaphore: tránh phân tích đồng thời quá nhiều (rate-limit API)
_analysis_lock = threading.Semaphore(2)

WATCHLIST = [
    "ACB","BID","CTG","HDB","LPB","MBB","MSB","OCB","SHB","STB","TCB","TPB","VCB","VIB","VPB",
    "BAB","EIB","NAB","SSB","VBB","VIC","VHM","VRE","BCM","NVL","PDR","DIG","DXG","KDH","NLG",
    "KBC","SZC","IDC","VGC","ITA","CEO","TCH","KHG","HDG","DXS","AGG","CRE","QCG","NTL","SJS",
    "SSI","VND","VCI","HCM","VIX","SHS","FTS","MBS","BSI","CTS","AGR","ORS","TVS","VDS","BVS",
    "HPG","HSG","NKG","VGS","POM","TLH","SMC","HT1","BCC","BMP","VCS","GAS","PLX","PVS","PVD",
    "PVT","BSR","POW","GEG","PC1","REE","TV2","NT2","BCG","ASM","MWG","MSN","VNM","PNJ","FRT",
    "DGW","PET","SAB","KDC","DBC","ANV","IDI","FPT","CMG","CTR","VGI","ELC","FOX","SAM","LCW",
    "GVR","DGC","DCM","DPM","PHR","DPR","CSV","LAS","BFC","AAA","GMD","HAH","VSC","VOS","VIP",
    "SGP","VNA","PHP","TMS","VCG","LCG","HHV","FCN","C4G","HBC","CTD","CII","NBB","DPG","HUT",
    "G36","HAG","HNG","TNG","MSH","VGT","TCM","GIL","PAN","LTG","NSC"
]

# ===========================================================================
# FLASK APP
# ===========================================================================
app = Flask(__name__)

# ===========================================================================
# TELEGRAM HELPERS
# ===========================================================================
def send_telegram(message: str, chat_id: str = None, retries: int = 3) -> bool:
    """Gửi tin nhắn Telegram. chat_id mặc định = TELEGRAM_CHAT_ID."""
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        log.warning("Telegram chưa cấu hình (BOT_TOKEN hoặc CHAT_ID trống)")
        return False
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": message, "parse_mode": "HTML"}
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            return True
        except Exception as e:
            log.warning(f"Telegram retry {attempt+1}: {e}")
            time.sleep(2)
    return False


def send_typing(chat_id: str):
    """Gửi trạng thái 'đang nhập' cho UX tốt hơn."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction"
        requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception:
        pass


# ===========================================================================
# MODULE DATA
# ===========================================================================
_INTERVAL_TCBS = {
    '1D':'1D','D':'1D','1W':'1W','W':'1W',
    '60':'1H','1H':'1H','30':'30m','15':'15m','5':'5m','1':'1m',
}

def _normalize_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    time_col = next((c for c in df.columns if 'time' in c or 'date' in c), df.columns[0])
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.rename(columns={time_col: 'time'}).set_index('time').sort_index()
    for col in ['open','high','low','close','volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['close'])
    return df if not df.empty else None


def _try_fetch(ticker: str, source: str, interval: str, start: str, end: str) -> Optional[pd.DataFrame]:
    try:
        client = Vnstock(api_key=VNSTOCK_API_KEY) if VNSTOCK_API_KEY else Vnstock()
        _stock = client.stock(symbol=ticker, source=source)
        df = _stock.quote.history(start=start, end=end, interval=interval)
        return _normalize_df(df)
    except Exception as e:
        log.debug(f"[fetch] {ticker} src={source} iv={interval}: {e}")
        return None


def fetch_ohlcv(ticker: str, start: str, end: str, resolution: str = '1D',
                max_retries: int = 3) -> Optional[pd.DataFrame]:
    wait_times = [10, 20, 40]
    is_index   = ticker.upper() in ('VNINDEX','VN30','HNX','UPCOM')
    is_intra   = resolution not in ('1D','D','1W','W')

    if is_intra:
        iv = _INTERVAL_TCBS.get(resolution, resolution)
        candidates = [('TCBS', iv)]
    elif is_index:
        candidates = [('TCBS','1D'),('VCI','1D')]
    else:
        candidates = [('VCI','1D'),('TCBS','1D')]

    for source, interval in candidates:
        for attempt in range(max_retries):
            df = _try_fetch(ticker, source, interval, start, end)
            if df is not None:
                return df
            time.sleep(wait_times[min(attempt, len(wait_times)-1)])
    return None


# ===========================================================================
# MODULE MARKET REGIME
# ===========================================================================
def get_market_regime(start: str, end: str) -> dict:
    default = {
        'regime':'NEUTRAL','allow_long':True,
        'vnindex_price':0,'rsi':50,'ma20':0,'ma50':0,'vnindex_ret20':0.0
    }
    df = fetch_ohlcv('VNINDEX', start, end, '1D')
    if df is None or len(df) < 55:
        return default
    try:
        df['ma20'] = ta.sma(df['close'], length=20)
        df['ma50'] = ta.sma(df['close'], length=50)
        df['rsi']  = ta.rsi(df['close'], length=14)
        lt = df.iloc[-1]
        p, m20, m50, rsi = lt['close'], lt['ma20'], lt['ma50'], lt['rsi']
        ret20 = (p / df['close'].iloc[-RS_LOOKBACK-1] - 1) if len(df) > RS_LOOKBACK+1 else 0.0
        if p > m20 and p > m50 and m20 > m50:
            regime, allow = 'BULL', True
        elif p < m20*0.95 and p < m50:
            regime, allow = 'BEAR', False
        else:
            regime, allow = 'NEUTRAL', True
        return {
            'regime':regime,'allow_long':allow,
            'vnindex_price':round(p,2),'rsi':round(rsi,1),
            'ma20':round(m20,2),'ma50':round(m50,2),
            'vnindex_ret20':round(ret20,4)
        }
    except Exception as e:
        log.error(f"[Market] {e}")
        return default


def calc_relative_strength(df_stock: pd.DataFrame, vnindex_ret20: float) -> float:
    if len(df_stock) < RS_LOOKBACK+2 or vnindex_ret20 == 0:
        return 1.0
    stock_ret = df_stock['close'].iloc[-1] / df_stock['close'].iloc[-RS_LOOKBACK-1] - 1
    if abs(vnindex_ret20) < 0.001:
        return 1.0 if stock_ret >= 0 else 0.5
    return round(stock_ret / abs(vnindex_ret20), 3)


# ===========================================================================
# MODULE INDICATORS
# ===========================================================================
def calc_mcdx_banker(df: pd.DataFrame, length: int = 14) -> float:
    if len(df) < length+2: return 50.0
    delta  = df['close'].diff()
    up_vol = df['volume'].where(delta > 0, 0.0)
    mcdx   = (up_vol.rolling(length).sum() / df['volume'].rolling(length).sum() * 100)\
              .replace([np.inf,-np.inf], np.nan).fillna(50)
    return round(float(mcdx.iloc[-1]), 1)


def calc_fib(swing_high: float, swing_low: float) -> dict:
    diff = swing_high - swing_low
    fibs = {lvl: swing_high - diff*lvl for lvl in FIB_LEVELS}
    fibs.update({
        'ote_low':   swing_high - diff*OTE_HIGH,
        'ote_high':  swing_high - diff*OTE_LOW,
        'ext_127':   swing_low  + diff*TP_EXT_127,
        'ext_162':   swing_low  + diff*TP_EXT_162,
        'swing_high':swing_high,'swing_low':swing_low,
        'midpoint':  (swing_high+swing_low)/2
    })
    return fibs


def in_ote_zone(price, fibs): return fibs['ote_low'] <= price <= fibs['ote_high']

def dist_to_ote(price, fibs):
    if price > fibs['ote_high']: return (price-fibs['ote_high'])/price
    if price < fibs['ote_low']:  return (fibs['ote_low']-price)/price
    return 0.0

def nearest_fib_label(price, fibs):
    labels = {0.236:'23.6%',0.382:'38.2%',0.500:'50%',0.618:'61.8%',0.786:'78.6%'}
    return labels[min(labels, key=lambda k: abs(price-fibs[k]))]


def find_bullish_ob(df: pd.DataFrame, lookback: int = 60) -> Optional[dict]:
    s = df.tail(lookback).reset_index(drop=True)
    for i in range(len(s)-3, 1, -1):
        c, n = s.iloc[i], s.iloc[i+1]
        if c['close'] >= c['open']: continue
        body_n = abs(n['close']-n['open'])
        if n['close'] <= n['open'] or body_n/max(n['open'],0.01) < 0.004: continue
        if n['high'] > s.iloc[max(0,i-3):i]['high'].max():
            return {'ob_high':round(c['high'],2),'ob_low':round(c['low'],2),
                    'ob_mid':round((c['high']+c['low'])/2,2)}
    return None


def dist_to_ob(price, ob):
    if ob['ob_low'] <= price <= ob['ob_high']: return 0.0
    if price > ob['ob_high']: return (price-ob['ob_high'])/price
    return (ob['ob_low']-price)/price


def find_bullish_fvg(df: pd.DataFrame, lookback: int = 50) -> list:
    fvgs, current = [], df['close'].iloc[-1]
    s = df.tail(lookback+2).reset_index(drop=True)
    for i in range(1, len(s)-1):
        p, n = s.iloc[i-1], s.iloc[i+1]
        if n['low'] > p['high'] and current >= p['high']*0.97:
            fvgs.append({'fvg_top':round(n['low'],2),'fvg_bot':round(p['high'],2),
                         'fvg_mid':round((n['low']+p['high'])/2,2)})
    return fvgs[-3:]


def detect_structure(df: pd.DataFrame, lookback: int = 40) -> dict:
    s = df.tail(lookback)
    highs, lows = s['high'].values, s['low'].values
    sh, sl = [], []
    for i in range(2, len(highs)-2):
        if highs[i] == max(highs[i-2:i+3]): sh.append(highs[i])
        if lows[i]  == min(lows[i-2:i+3]):  sl.append(lows[i])
    return {
        'bos_bull':   len(sh)>=2 and sh[-1]>sh[-2],
        'choch_bear': len(sl)>=2 and sl[-1]<sl[-2],
        'hh_hl':      (len(sh)>=2 and sh[-1]>sh[-2]) and (len(sl)>=2 and sl[-1]>sl[-2]),
        'last_sh': sh[-1] if sh else highs.max(),
        'last_sl': sl[-1] if sl else lows.min(),
    }


def detect_sweep(df: pd.DataFrame, lookback: int = 24) -> dict:
    s = df.tail(lookback).reset_index(drop=True)
    prev_low = s['low'].iloc[:-3].min()
    last = s.iloc[-1]
    if last['low'] < prev_low and last['close'] > last['open']:
        return {'swept':True,'type':'BULL_SWEEP','level':round(prev_low,2)}
    return {'swept':False,'type':None,'level':None}


def vol_dryup(df, window=6, threshold=0.65):
    if len(df) < 25: return False
    ma20 = df['volume'].tail(25).mean()
    return df['volume'].tail(window).mean() < threshold*ma20 and ma20 > 0

def vol_spike(df, mult=1.5):
    if len(df) < 25: return False
    ma20 = df['volume'].tail(25).mean()
    return df['volume'].iloc[-1] > mult*ma20 and ma20 > 0


def detect_reversal(df: pd.DataFrame) -> dict:
    last, prev = df.iloc[-1], df.iloc[-2]
    body  = abs(last['close']-last['open'])
    rng   = last['high']-last['low']
    lower = min(last['close'],last['open'])-last['low']
    res   = {'pinbar':False,'engulfing':False}
    if rng > 0:
        if lower > 0.55*rng and body < 0.40*rng and last['close'] > last['open']:
            res['pinbar'] = True
        if (last['close']>last['open'] and prev['close']<prev['open']
                and last['close']>prev['open'] and last['open']<prev['close']):
            res['engulfing'] = True
    return res


def calc_trade(price, ob, fibs, scenario):
    if scenario == 'UPTREND':
        sl = price*0.96
        if ob and ob['ob_low'] > price*0.93:
            sl = max(ob['ob_low']*0.99, price*(1-MAX_SL_PCT))
    else:
        sl = price*0.97
    sl   = max(sl, price*(1-MAX_SL_PCT))
    risk = price-sl
    if risk <= 0: return {'valid':False}
    tp1 = max(fibs['ext_127'], price+risk*MIN_RR_RATIO)
    tp2 = max(fibs['ext_162'], price+risk*(MIN_RR_RATIO+1.5))
    tp1 = min(tp1, price*1.20); tp1 = max(tp1, price*(1+MIN_TP_PCT))
    rr1 = (tp1-price)/risk; rr2 = (tp2-price)/risk
    return {
        'sl':round(sl,2),'tp1':round(tp1,2),'tp2':round(tp2,2),
        'sl_pct':round((price-sl)/price*100,1),
        'tp1_pct':round((tp1-price)/price*100,1),
        'tp2_pct':round((tp2-price)/price*100,1),
        'rr1':round(rr1,1),'rr2':round(rr2,1),'valid':rr1>=MIN_RR_RATIO
    }


# ===========================================================================
# MODULE PHÂN TÍCH CHÍNH
# ===========================================================================
def get_date_range():
    now = datetime.now(VN_TZ)
    td  = get_last_trading_day(now)
    end      = td.strftime('%Y-%m-%d')
    start_d1 = (td - timedelta(days=200)).strftime('%Y-%m-%d')
    start_h1 = (td - timedelta(days=45)).strftime('%Y-%m-%d')
    start_m15= (td - timedelta(days=10)).strftime('%Y-%m-%d')
    return end, start_d1, start_h1, start_m15


def get_last_trading_day(ref=None):
    if ref is None: ref = datetime.now(VN_TZ)
    d = ref
    if d.weekday() == 5: d -= timedelta(days=1)
    elif d.weekday() == 6: d -= timedelta(days=2)
    else:
        mo = d.replace(hour=9, minute=0, second=0, microsecond=0)
        if d < mo:
            d -= timedelta(days=1)
            if d.weekday() == 5: d -= timedelta(days=1)
            elif d.weekday() == 6: d -= timedelta(days=2)
    return d


def analyze(ticker: str, start_d1: str, start_h1: str, start_m15: str,
            end: str, market: dict) -> Optional[dict]:
    """Phân tích đầy đủ một mã. Trả về dict hoặc None."""
    try:
        df_d1  = fetch_ohlcv(ticker, start_d1,  end, '1D')
        df_h1  = fetch_ohlcv(ticker, start_h1,  end, '60')
        df_m15 = fetch_ohlcv(ticker, start_m15, end, '15')

        if df_d1 is None or len(df_d1) < 55:
            return None

        df_d1['ma20']  = ta.sma(df_d1['close'], length=20)
        df_d1['ma50']  = ta.sma(df_d1['close'], length=50)
        df_d1['ema21'] = ta.ema(df_d1['close'], length=21)
        bb = ta.bbands(df_d1['close'], length=20)
        df_d1['bb_w'] = ((bb.iloc[:,2]-bb.iloc[:,0])/bb.iloc[:,1]) if bb is not None else np.nan
        d = df_d1.iloc[-1]
        if pd.isna(d['ma50']): return None

        price = d['close']; ma20 = d['ma20']; ma50 = d['ma50']; ema21 = d['ema21']

        if price > ma20 and price > ma50 and ma20 > ma50:   trend = 'UPTREND'
        elif price < ma20 and price < ma50 and ma20 < ma50: trend = 'DOWNTREND'
        else:                                                trend = 'SIDEWAYS'

        rs = calc_relative_strength(df_d1, market['vnindex_ret20'])
        if not market['allow_long'] and trend == 'UPTREND' and rs < RS_MIN_BEAR: return None
        if not market['allow_long'] and trend == 'SIDEWAYS': return None

        mcdx_d1 = calc_mcdx_banker(df_d1, length=14)

        ob_h1=None; fvg_h1=[]; struct_h1={'bos_bull':False,'choch_bear':False,'hh_hl':False,'last_sh':0,'last_sl':0}
        dry_h1=False; rsi_h1=np.nan; ema21_h1=np.nan
        if df_h1 is not None and len(df_h1) >= 30:
            df_h1['rsi']   = ta.rsi(df_h1['close'], length=14)
            df_h1['ema21'] = ta.ema(df_h1['close'], length=21)
            rsi_h1=df_h1['rsi'].iloc[-1]; ema21_h1=df_h1['ema21'].iloc[-1]
            ob_h1=find_bullish_ob(df_h1); fvg_h1=find_bullish_fvg(df_h1)
            struct_h1=detect_structure(df_h1); dry_h1=vol_dryup(df_h1)

        sweep={'swept':False,'type':None,'level':None}; rev={'pinbar':False,'engulfing':False}; spike=False
        if df_m15 is not None and len(df_m15) >= 24:
            sweep=detect_sweep(df_m15); rev=detect_reversal(df_m15); spike=vol_spike(df_m15)

        sh60=df_d1['high'].tail(60).max(); sl60=df_d1['low'].tail(60).min()
        fibs=calc_fib(sh60,sl60); ote=in_ote_zone(price,fibs); fib_l=nearest_fib_label(price,fibs)
        zone="DISCOUNT ✅" if price < fibs['midpoint'] else "PREMIUM ⚠️"
        d_ote=dist_to_ote(price,fibs); d_ob=dist_to_ob(price,ob_h1) if ob_h1 else 1.0
        near_value=min(d_ote,d_ob)

        score=0; notes=[]

        if struct_h1['hh_hl']:     score+=2; notes.append("✅ HH-HL H1 — uptrend lành mạnh")
        elif struct_h1['bos_bull']: score+=1; notes.append("✅ BOS Bullish H1")
        if struct_h1['choch_bear']: score-=2; notes.append("⚠️ CHoCH Bearish H1 — cảnh báo!")

        if ob_h1 and ob_h1['ob_low']<=price<=ob_h1['ob_high']:
            score+=3; notes.append(f"📦 Trong OB H1 [{ob_h1['ob_low']}–{ob_h1['ob_high']}]")
        for fvg in fvg_h1:
            if fvg['fvg_bot']<=price<=fvg['fvg_top']:
                score+=2; notes.append(f"🕳️ Trong FVG H1 [{fvg['fvg_bot']}–{fvg['fvg_top']}]"); break
        if not np.isnan(ema21_h1) and ema21_h1*0.985<=price<=ema21_h1*1.015:
            score+=1; notes.append(f"📌 Chạm EMA21 H1 ({ema21_h1:.2f})")
        if ote:
            score+=2; notes.append(f"🎯 ICT OTE Fibo {fib_l}")
        if sweep['swept'] and sweep['type']=='BULL_SWEEP':
            score+=3; notes.append(f"💧 Liquidity Sweep Bullish M15 tại {sweep['level']}")
        if rev['pinbar']:    score+=2; notes.append("🕯️ Pinbar Bullish M15")
        if rev['engulfing']: score+=2; notes.append("🕯️ Engulfing Bullish M15")
        if dry_h1: score+=2; notes.append("📉 Volume Dry-up H1 — cung cạn")
        if spike:  score+=2; notes.append("📊 Volume đột biến M15")
        if not np.isnan(rsi_h1):
            if trend=='UPTREND' and 32<=rsi_h1<=52: score+=1; notes.append(f"📈 RSI H1 {rsi_h1:.0f} — pullback")
            elif rsi_h1<30: score+=1; notes.append(f"📉 RSI H1 {rsi_h1:.0f} — oversold")

        if mcdx_d1 > MCDX_THRESH_2: score+=2; notes.append(f"💰 MCDX {mcdx_d1:.0f}% — Big Money (+2đ)")
        elif mcdx_d1 > MCDX_THRESH_1: score+=1; notes.append(f"💰 MCDX {mcdx_d1:.0f}% — Dòng tiền lớn (+1đ)")
        if rs > 1.10: score+=1; notes.append(f"💪 RS {rs:.2f} — mạnh hơn VNI 🔥")

        is_approaching = (score < MIN_SMC_SCORE and near_value < 0.03 and not struct_h1['choch_bear'])
        if score < MIN_SMC_SCORE and not is_approaching: return None

        scenario=None; signal=None

        if trend=='UPTREND':
            near_ema = not np.isnan(ema21_h1) and ema21_h1*0.985<=price<=ema21_h1*1.02
            in_ob    = ob_h1 and ob_h1['ob_low']<=price
            if near_ema or ote or in_ob or is_approaching:
                scenario='UPTREND'
                if not is_approaching:
                    t=calc_trade(price,ob_h1,fibs,scenario)
                    if not t['valid']: return None
                    signal=(f"🚀 <b>UPTREND PULLBACK</b>  (T+10~14 ngày)\n"
                            f"   📍 Vùng giá  : {zone}\n"
                            f"   🔍 Fibo gần  : {fib_l}\n"
                            f"   💪 RS vs VNI : {rs:.2f}{'  🔥' if rs>1.10 else ''}\n"
                            f"   💵 Vào lệnh  : <b>{price:.2f}</b>\n"
                            f"   🛑 SL        : {t['sl']} (-{t['sl_pct']}%)\n"
                            f"   🎯 TP1       : {t['tp1']} (+{t['tp1_pct']}%)\n"
                            f"   🎯 TP2       : {t['tp2']} (+{t['tp2_pct']}%)\n"
                            f"   ⚖️  R:R      : 1:{t['rr1']} → 1:{t['rr2']}\n"
                            f"   💡 <i>Mua 50% ngay, 50% khi chạm OB/OTE. Chốt 50% tại TP1.</i>")

        elif trend=='SIDEWAYS':
            low20=df_d1['low'].tail(20).min(); high20=df_d1['high'].tail(20).max()
            box_w=(high20-low20)/low20
            bb_sq=not pd.isna(d.get('bb_w',np.nan)) and d['bb_w']<0.05
            rsi_os=not np.isnan(rsi_h1) and rsi_h1<38
            if price<=low20*1.03 and rsi_os and box_w>0.07:
                scenario='SIDEWAYS'
                sl_box=round(low20*0.97,2); tp1_box=round((low20+high20)/2,2); tp2_box=round(high20,2)
                risk_box=price-sl_box; rr_box=(tp2_box-price)/risk_box if risk_box>0 else 0
                if rr_box<MIN_RR_RATIO and not is_approaching: return None
                signal=(f"📦 <b>SIDEWAYS — MUA ĐÁY HỘP</b>  (T+10~14 ngày)\n"
                        f"   📏 Hộp      : {low20:.2f} – {high20:.2f} ({box_w*100:.1f}%)\n"
                        f"{'   🔒 BB Squeeze — tích tụ năng lượng.'+chr(10) if bb_sq else ''}"
                        f"   📉 RSI H1   : {rsi_h1:.0f}  (oversold)\n"
                        f"   💵 Vào lệnh : <b>{price:.2f}</b>\n"
                        f"   🛑 SL       : {sl_box} (-{((price-sl_box)/price*100):.1f}%)\n"
                        f"   🎯 TP1      : {tp1_box} (+{((tp1_box-price)/price*100):.1f}%)\n"
                        f"   🎯 TP2      : {tp2_box} (+{((tp2_box-price)/price*100):.1f}%)\n"
                        f"   ⚖️  R:R     : 1:{rr_box:.1f}\n"
                        f"   💡 <i>Chốt toàn bộ tại cạnh trên hộp.</i>")
            elif is_approaching: scenario='SIDEWAYS'

        elif trend=='DOWNTREND':
            deep=price<ma20*0.88; rsi_ex=not np.isnan(rsi_h1) and rsi_h1<28
            has_sw=sweep['swept'] and sweep['type']=='BULL_SWEEP'; has_rv=rev['pinbar'] or rev['engulfing']
            if deep and rsi_ex and (has_sw or has_rv) and score>=4:
                scenario='DOWNTREND'
                t=calc_trade(price,ob_h1,fibs,scenario)
                if not t['valid']: return None
                disc=(ma20-price)/ma20*100
                signal=(f"🔪 <b>DOWNTREND — BẮT SÓNG HỒI</b>  ⚠️ Rủi ro cao\n"
                        f"   📉 Chiết khấu vs MA20: {disc:.1f}%\n"
                        f"   📉 RSI H1            : {rsi_h1:.0f}  (cực oversold)\n"
                        f"   💧 Sweep Bullish M15 : {'✅' if has_sw else '—'}\n"
                        f"   🕯️ Nến đảo chiều M15 : {'✅ Pinbar/Engulfing' if has_rv else '—'}\n"
                        f"   💵 Vào lệnh          : <b>{price:.2f}</b>  (MAX 25% vốn)\n"
                        f"   🛑 SL                : {t['sl']} (-{t['sl_pct']}%)\n"
                        f"   🎯 TP1 (EMA21 D1)   : {ema21:.2f} (+{((ema21-price)/price*100):.1f}%)\n"
                        f"   🎯 TP2 (MA20 D1)    : {ma20:.2f} (+{((ma20-price)/price*100):.1f}%)\n"
                        f"   ⚖️  R:R              : 1:{t['rr1']}\n"
                        f"   💡 <i>Bán ngay khi chạm EMA21. NO Margin.</i>")
            elif is_approaching: scenario='DOWNTREND'

        if scenario is None: return None

        if signal is None and is_approaching:
            ob_str =(f"{ob_h1['ob_low']}–{ob_h1['ob_high']}" if ob_h1 else "—")
            signal=(f"⏳ <b>TIỆM CẬN ĐIỀU KIỆN</b>\n"
                    f"   Xu hướng D1  : {trend}\n"
                    f"   Vùng chờ OB  : {ob_str}\n"
                    f"   Vùng chờ OTE : {fibs['ote_low']:.2f}–{fibs['ote_high']:.2f}\n"
                    f"   Cách vùng    : ~{near_value*100:.1f}%\n"
                    f"   Score        : {score}/{MIN_SMC_SCORE} (cần thêm {MIN_SMC_SCORE-score}đ)\n"
                    f"   💡 <i>Theo dõi khi giá tiến vào vùng.</i>")

        star  = '⭐'*min(score,7)
        n_str = "\n   ".join(notes) if notes else "—"
        message=(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                 f"📌 <b>{ticker}</b>  ·  {trend}  ·  {star} ({score}đ)\n"
                 f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                 f"{signal}\n\n"
                 f"<i>🧠 SMC/ICT:\n   {n_str}</i>\n\n"
                 f"<i>📐 Fibo 60p  H={sh60:.2f} | L={sl60:.2f}\n"
                 f"   OTE: {fibs['ote_low']:.2f}–{fibs['ote_high']:.2f}"
                 f"  | Ext127: {fibs['ext_127']:.2f}"
                 f"  | Ext162: {fibs['ext_162']:.2f}</i>")

        return {
            'ticker':ticker,'scenario':scenario,'score':score,'message':message,
            'approaching':is_approaching,'near_value':near_value,'rs':rs,
            'price':price,'trend':trend,'mcdx':mcdx_d1,
        }
    except Exception as e:
        log.error(f"[analyze] {ticker}: {e}")
        if DEBUG_MODE: traceback.print_exc()
        return None


# ===========================================================================
# VERDICT — thang điểm nên mua hay không (dùng cho on-demand)
# ===========================================================================
def build_verdict(res: dict) -> str:
    score = res['score']
    if score >= 9:
        verdict = "🟢 <b>RẤT NÊN MUA</b> — Confluence cực mạnh, tín hiệu hội tụ nhiều chiều"
    elif score >= 6:
        verdict = "🟢 <b>NÊN MUA</b> — Tín hiệu tốt, đủ confluence để vào lệnh"
    elif score >= MIN_SMC_SCORE:
        verdict = "🟡 <b>CÓ THỂ XEM XÉT</b> — Tín hiệu ở mức tối thiểu, cần thêm xác nhận"
    elif res['approaching']:
        verdict = "⏳ <b>CHỜ THÊM</b> — Đang tiệm cận vùng tốt nhưng chưa đủ điều kiện"
    else:
        verdict = "🔴 <b>KHÔNG NÊN MUA</b> — Chưa đủ điều kiện"

    return (f"\n\n{'═'*27}\n"
            f"🏆 <b>VERDICT</b>\n"
            f"   {verdict}\n"
            f"   Điểm SMC/ICT: <b>{score}/15+</b>\n"
            f"{'═'*27}")


def analyze_on_demand(ticker: str, chat_id: str):
    """Phân tích một mã theo yêu cầu và gửi kết quả về Telegram."""
    with _analysis_lock:
        ticker = ticker.upper().strip()
        log.info(f"[OnDemand] Phân tích {ticker} cho chat {chat_id}")

        send_typing(chat_id)
        send_telegram(f"⏳ Đang phân tích <b>{ticker}</b>...\n"
                      f"<i>Multi-timeframe D1 + H1 + M15 — vui lòng chờ ~30 giây</i>",
                      chat_id=chat_id)

        end, start_d1, start_h1, start_m15 = get_date_range()
        market = get_market_regime(start_d1, end)
        res    = analyze(ticker, start_d1, start_h1, start_m15, end, market)

        if res is None:
            # Thử lấy giá cơ bản để biết mã có tồn tại không
            df_basic = fetch_ohlcv(ticker, start_d1, end, '1D')
            if df_basic is None:
                send_telegram(f"❌ <b>{ticker}</b> — không tìm thấy dữ liệu.\n"
                              f"Kiểm tra lại mã CP (ví dụ: ACB, VCB, HPG...)", chat_id=chat_id)
            else:
                p = df_basic['close'].iloc[-1]
                send_telegram(
                    f"📊 <b>{ticker}</b>  — Giá: {p:.2f}\n\n"
                    f"❌ <b>KHÔNG ĐỦ ĐIỀU KIỆN</b> vào lệnh\n\n"
                    f"Lý do có thể:\n"
                    f"• Không đủ dữ liệu lịch sử (< 55 phiên)\n"
                    f"• Xu hướng không rõ ràng / DOWNTREND mà chưa đủ tín hiệu đảo chiều\n"
                    f"• Score SMC < {MIN_SMC_SCORE} và không tiệm cận vùng giá trị\n"
                    f"• Bị lọc bởi Market Regime: VNI đang {market['regime']}\n\n"
                    f"💡 <i>Theo dõi thêm hoặc chờ điều kiện hội tụ rõ hơn.</i>",
                    chat_id=chat_id
                )
            return

        verdict = build_verdict(res)
        full_msg = res['message'] + verdict
        send_telegram(full_msg, chat_id=chat_id)
        log.info(f"[OnDemand] {ticker} → Score={res['score']} {res['scenario']}")


# ===========================================================================
# DAILY SCAN (Scheduled)
# ===========================================================================
def run_daily_scan():
    log.info("=== BẮT ĐẦU DAILY SCAN ===")
    end, start_d1, start_h1, start_m15 = get_date_range()
    market = get_market_regime(start_d1, end)
    emoji  = {'BULL':'🟢','BEAR':'🔴','NEUTRAL':'🟡'}.get(market['regime'],'⚪')

    send_telegram(
        f"📊 <b>VN-INDEX — TRẠNG THÁI THỊ TRƯỜNG</b>\n"
        f"   Chỉ số  : {market['vnindex_price']}\n"
        f"   Regime  : {emoji} <b>{market['regime']}</b>\n"
        f"   RSI(14) : {market['rsi']}\n"
        f"   MA20    : {market['ma20']}  |  MA50: {market['ma50']}\n"
        f"   Ret 20p : {market['vnindex_ret20']*100:+.1f}%"
        + (f"\n   ⚠️ BEAR mode — chỉ Long RS >{RS_MIN_BEAR}" if market['regime']=='BEAR' else "")
    )

    all_res = []
    for i, ticker in enumerate(WATCHLIST):
        log.info(f"[Scan {i+1}/{len(WATCHLIST)}] {ticker}")
        with _analysis_lock:
            res = analyze(ticker, start_d1, start_h1, start_m15, end, market)
        if res:
            all_res.append(res)
        time.sleep(2)

    signals     = sorted([r for r in all_res if not r['approaching']], key=lambda x: -x['score'])
    approaching = sorted([r for r in all_res if r['approaching']],     key=lambda x: x['near_value'])
    top   = signals[:TOP_N_SIGNALS]
    top_a = approaching[:TOP_N_APPROACHING]
    up    = [r for r in top if r['scenario']=='UPTREND']
    sw    = [r for r in top if r['scenario']=='SIDEWAYS']
    dn    = [r for r in top if r['scenario']=='DOWNTREND']

    td = get_last_trading_day()
    send_telegram(
        f"🤖 <b>BÁO CÁO SCANNER v3.1 — {td.strftime('%d/%m/%Y')}</b>\n"
        f"🔍 Quét <b>{len(WATCHLIST)}</b> mã\n"
        f"   ✅ Tín hiệu đủ TK : <b>{len(signals)}</b> mã\n"
        f"   ⏳ Tiệm cận       : <b>{len(approaching)}</b> mã\n\n"
        f"🏆 Top {len(top)} mã:\n"
        f"   🚀 Uptrend   : {len(up)} mã\n"
        f"   📦 Sideways  : {len(sw)} mã\n"
        f"   🔪 Downtrend : {len(dn)} mã\n\n"
        f"<i>⚠️ Công cụ hỗ trợ — không phải khuyến nghị đầu tư.</i>"
    )

    def send_group(group, label):
        if not group: return
        send_telegram(f"<b>{'─'*22}\n{label}\n{'─'*22}</b>")
        time.sleep(0.5)
        for j in range(0, len(group), 3):
            send_telegram("\n\n".join(r['message'] for r in group[j:j+3]))
            time.sleep(1.5)

    send_group(up, "🚀 UPTREND — PULLBACK VÀO LỆNH")
    send_group(sw, "📦 SIDEWAYS — MUA ĐÁY HỘP")
    send_group(dn, "🔪 DOWNTREND — BẮT SÓNG HỒI")
    if top_a: send_group(top_a, f"⏳ VÙNG CHỜ — TOP {len(top_a)} MÃ TIỆM CẬN")

    if not top and not top_a:
        send_telegram("🤖 Không có mã đạt tiêu chuẩn hôm nay.\n💰 <b>Tiền mặt là vị thế tốt nhất.</b>")
    log.info("=== DAILY SCAN HOÀN TẤT ===")


# ===========================================================================
# FLASK ROUTES
# ===========================================================================
@app.route('/', methods=['GET'])
def health():
    now = datetime.now(VN_TZ)
    return jsonify({
        'status': 'ok',
        'service': 'VN Stock Scanner v3.1',
        'time_vn': now.strftime('%Y-%m-%d %H:%M:%S %Z'),
        'watchlist_count': len(WATCHLIST)
    })


@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Đăng ký Telegram webhook — gọi một lần sau khi deploy."""
    if not WEBHOOK_URL:
        return jsonify({'error': 'WEBHOOK_URL chưa được cấu hình'}), 400
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    payload = {
        "url": f"{WEBHOOK_URL.rstrip('/')}/webhook",
        "allowed_updates": ["message"],
        "drop_pending_updates": True
    }
    r = requests.post(url, json=payload, timeout=10)
    return jsonify(r.json())


@app.route('/webhook', methods=['POST'])
def webhook():
    """Nhận update từ Telegram."""
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({'ok': True})

        msg = data.get('message') or data.get('edited_message')
        if not msg:
            return jsonify({'ok': True})

        chat_id  = str(msg['chat']['id'])
        raw_text = msg.get('text', '').strip()
        text_up  = raw_text.upper()

        log.info(f"[Webhook] chat={chat_id} msg='{raw_text}'")

        # ── /start ───────────────────────────────────────────────────────────
        if text_up in ('/START', 'START'):
            send_telegram(
                "👋 <b>Chào mừng đến VN Stock Scanner v3.1!</b>\n\n"
                "📌 <b>Cách dùng:</b>\n"
                "   • Gõ mã CP bất kỳ → nhận phân tích SMC/ICT ngay\n"
                "     Ví dụ: <code>ACB</code>, <code>VCB</code>, <code>HPG</code>\n\n"
                "⌨️ <b>Lệnh:</b>\n"
                "   /scan   — Quét toàn bộ watchlist ngay\n"
                "   /status — Xem trạng thái VN-Index\n"
                "   /help   — Hướng dẫn chi tiết\n\n"
                "<i>⚠️ Công cụ hỗ trợ phân tích — không phải khuyến nghị đầu tư.</i>",
                chat_id=chat_id
            )
            return jsonify({'ok': True})

        # ── /help ────────────────────────────────────────────────────────────
        if text_up in ('/HELP', 'HELP'):
            send_telegram(
                "📖 <b>HƯỚNG DẪN SỬ DỤNG</b>\n\n"
                "1️⃣ Gõ mã cổ phiếu (VD: <code>ACB</code>) → bot phân tích đa khung thời gian\n\n"
                "2️⃣ Kết quả bao gồm:\n"
                "   • Xu hướng D1 (Uptrend/Sideways/Downtrend)\n"
                "   • Điểm SMC/ICT confluence (0–15+)\n"
                "   • Order Block H1, FVG H1, Liquidity Sweep M15\n"
                "   • Fibonacci 60 phiên + ICT OTE Zone\n"
                "   • Volume Dry-up, MCDX Banker\n"
                "   • SL/TP/R:R cụ thể\n"
                "   • Verdict: NÊN/KHÔNG NÊN mua\n\n"
                "3️⃣ Daily scan tự động lúc 8:15 SA mỗi ngày giao dịch\n\n"
                "<i>Score ≥9: Rất nên | ≥6: Nên | ≥3: Xem xét | <3: Chưa đủ</i>",
                chat_id=chat_id
            )
            return jsonify({'ok': True})

        # ── /status ──────────────────────────────────────────────────────────
        if text_up in ('/STATUS', 'STATUS'):
            send_telegram(f"⏳ Đang lấy dữ liệu VN-Index...", chat_id=chat_id)
            def _status():
                end, start_d1, *_ = get_date_range()
                m = get_market_regime(start_d1, end)
                emoji = {'BULL':'🟢','BEAR':'🔴','NEUTRAL':'🟡'}.get(m['regime'],'⚪')
                send_telegram(
                    f"📊 <b>VN-INDEX HIỆN TẠI</b>\n"
                    f"   Chỉ số : {m['vnindex_price']}\n"
                    f"   Regime : {emoji} <b>{m['regime']}</b>\n"
                    f"   RSI(14): {m['rsi']}\n"
                    f"   MA20   : {m['ma20']}  |  MA50: {m['ma50']}\n"
                    f"   Ret 20p: {m['vnindex_ret20']*100:+.1f}%",
                    chat_id=chat_id
                )
            threading.Thread(target=_status, daemon=True).start()
            return jsonify({'ok': True})

        # ── /scan ────────────────────────────────────────────────────────────
        if text_up in ('/SCAN', 'SCAN'):
            send_telegram(
                f"🔍 Bắt đầu quét <b>{len(WATCHLIST)}</b> mã...\n"
                f"<i>Quá trình mất ~10-15 phút. Kết quả sẽ gửi về đây.</i>",
                chat_id=chat_id
            )
            # Override CHAT_ID để kết quả gửi về đúng chat người dùng
            orig_chat = TELEGRAM_CHAT_ID
            def _scan_to_chat():
                global TELEGRAM_CHAT_ID
                TELEGRAM_CHAT_ID = chat_id
                run_daily_scan()
                TELEGRAM_CHAT_ID = orig_chat
            threading.Thread(target=_scan_to_chat, daemon=True).start()
            return jsonify({'ok': True})

        # ── Phân tích mã CP ──────────────────────────────────────────────────
        # Nhận dạng: 2-10 ký tự chữ cái (có thể có / ở đầu)
        ticker_match = re.match(r'^/?([A-ZĐ]{2,10})$', text_up)
        if ticker_match:
            ticker = ticker_match.group(1)
            threading.Thread(
                target=analyze_on_demand,
                args=(ticker, chat_id),
                daemon=True
            ).start()
            return jsonify({'ok': True})

        # ── Không nhận dạng được ─────────────────────────────────────────────
        send_telegram(
            f"❓ Không hiểu lệnh: <code>{raw_text}</code>\n\n"
            f"Gõ mã CP như <code>ACB</code>, <code>VCB</code>\n"
            f"hoặc /help để xem hướng dẫn.",
            chat_id=chat_id
        )

    except Exception as e:
        log.error(f"[Webhook Error] {e}")
        if DEBUG_MODE: traceback.print_exc()

    return jsonify({'ok': True})


# ===========================================================================
# SCHEDULER — Daily Scan 8:15 SA giờ VN (T2-T6)
# ===========================================================================
def start_scheduler():
    scheduler = BackgroundScheduler(timezone=VN_TZ)
    # Chạy lúc 8:15 SA, T2–T6 (day_of_week=0–4)
    scheduler.add_job(
        run_daily_scan,
        trigger='cron',
        day_of_week='mon-fri',
        hour=8, minute=15,
        id='daily_scan',
        misfire_grace_time=300
    )
    scheduler.start()
    log.info("✅ Scheduler started — Daily scan: T2-T6 lúc 08:15 SA (Asia/Ho_Chi_Minh)")
    return scheduler


# ===========================================================================
# ENTRY POINT
# ===========================================================================
scheduler_instance = None

def create_app():
    global scheduler_instance
    if scheduler_instance is None:
        scheduler_instance = start_scheduler()
    return app


if __name__ == '__main__':
    create_app()
    log.info(f"🚀 VN Stock Scanner v3.1 đang chạy trên port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
else:
    # Được gọi bởi gunicorn
    create_app()
