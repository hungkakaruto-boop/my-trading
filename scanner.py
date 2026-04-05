"""
=============================================================================
VN STOCK SCANNER v3.0 — Tối ưu T+10-14 ngày (Swing Trading)
Tích hợp: Multi-Timeframe THẬT + SMC + ICT + Fibonacci + Market Filter
=============================================================================
NÂNG CẤP so với v2:
  ✅ H4 THẬT SỰ — resample từ H1 (không còn proxy D1)
  ✅ Bộ lọc VN-Index — không đánh ngược gió thị trường
  ✅ Volume Dry-up — xác nhận Wyckoff Spring (cung cạn)
  ✅ SL/TP chặt chẽ — SL 3-5%, TP 10-15%, R:R >= 2.5
  ✅ Ranking SMC Score — chỉ gửi Top 10 mã tốt nhất
  ✅ Multi-timeframe THẬT: D1 → H4 → H1
  ✅ Chiến thuật vào lệnh cụ thể cho từng kịch bản
=============================================================================
"""

import os
import time
import requests
import numpy as np
import pandas as pd
import pandas_ta as ta
from vnstock import Vnstock
from datetime import datetime, timedelta


# ===========================================================================
# CẤU HÌNH HỆ THỐNG
# ===========================================================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID')
VNSTOCK_API_KEY = os.getenv('VNSTOCK_API_KEY', '')   # ← dán key vào đây nếu cần


MIN_RR_RATIO      = 2.5   # R:R tối thiểu (giữ nguyên cho swing T+10-14)
MAX_SL_PCT        = 0.05  # SL không sâu hơn 5%
MIN_TP_PCT        = 0.10  # TP tối thiểu 10%
MIN_SMC_SCORE     = 3     # Điểm confluence tối thiểu (Hard constraint)
TOP_N_SIGNALS     = 10    # Gửi Top N mã điểm cao nhất
TOP_N_APPROACHING = 5     # Gửi Top N mã "tiệm cận điều kiện"

# Relative Strength
RS_LOOKBACK       = 20    # Phiên tính RS vs VN-Index
RS_MIN_BEAR       = 1.05  # RS tối thiểu để Long khi thị trường Bear

# Fibonacci ICT OTE
OTE_LOW    = 0.618
OTE_HIGH   = 0.786
FIB_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]
TP_EXT_127 = 1.272
TP_EXT_162 = 1.618

# MCDX Banker threshold (% buying pressure)
MCDX_THRESH_1 = 55  # +1 điểm
MCDX_THRESH_2 = 70  # +2 điểm


WATCHLIST = [
    "ACB", "BID", "CTG", "HDB", "LPB", "MBB", "MSB", "OCB", "SHB", "STB", "TCB", "TPB", "VCB", "VIB", "VPB", 
    "BAB", "EIB", "NAB", "SSB", "VBB", "VIC", "VHM", "VRE", "BCM", "NVL", "PDR", "DIG", "DXG", "KDH", "NLG", 
    "KBC", "SZC", "IDC", "VGC", "ITA", "CEO", "TCH", "KHG", "HDG", "DXS", "AGG", "CRE", "QCG", "NTL", "SJS", 
    "SSI", "VND", "VCI", "HCM", "VIX", "SHS", "FTS", "MBS", "BSI", "CTS", "AGR", "ORS", "TVS", "VDS", "BVS", 
    "HPG", "HSG", "NKG", "VGS", "POM", "TLH", "SMC", "HT1", "BCC", "BMP", "VCS", "GAS", "PLX", "PVS", "PVD", 
    "PVT", "BSR", "POW", "GEG", "PC1", "REE", "TV2", "NT2", "BCG", "ASM", "MWG", "MSN", "VNM", "PNJ", "FRT", 
    "DGW", "PET", "SAB", "KDC", "DBC", "ANV", "IDI", "FPT", "CMG", "CTR", "VGI", "ELC", "FOX", "SAM", "LCW", 
    "GVR", "DGC", "DCM", "DPM", "PHR", "DPR", "CSV", "LAS", "BFC", "AAA", "GMD", "HAH", "VSC", "VOS", "VIP", 
    "SGP", "VNA", "PHP", "TMS", "VCG", "LCG", "HHV", "FCN", "C4G", "HBC", "CTD", "CII", "NBB", "DPG", "HUT", 
    "G36", "HAG", "HNG", "TNG", "MSH", "VGT", "TCM", "GIL", "PAN", "LTG", "NSC"
]

# Khởi tạo vnstock (global, dùng chung toàn bộ script)
stock = Vnstock().stock(symbol='ACB', source='VCI')


# ===========================================================================
# TELEGRAM
# ===========================================================================
def send_telegram(message: str, retries: int = 3) -> bool:
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"  [Telegram retry {attempt+1}] {e}")
            time.sleep(2)
    return False


# ===========================================================================
# MODULE 1: LẤY DỮ LIỆU
# ===========================================================================
def fetch_ohlcv(ticker: str, start: str, end: str, resolution: str = '1D',
                max_retries: int = 4) -> pd.DataFrame | None:
    """
    Lấy OHLCV từ vnstock.
    resolution : '1D' | '60' (H1) | '15' (M15)
    max_retries: tự động chờ & thử lại khi bị rate limit (429)
    """
    wait_times = [10, 20, 40, 60]   # giây chờ (giây) sau mỗi lần bị chặn

    for attempt in range(max_retries):
        try:
            # Truyền api_key nếu có — tăng rate limit từ 20 lên 60+/phút
            client = (Vnstock(api_key=VNSTOCK_API_KEY)
                      if VNSTOCK_API_KEY else Vnstock())
            _stock = client.stock(symbol=ticker, source='VCI')
            df = _stock.quote.history(
                symbol=ticker, start=start, end=end,
                interval=resolution
            )

            if df is None or df.empty:
                return None

            df.columns = [c.lower() for c in df.columns]
            time_col = next(
                (c for c in df.columns if 'time' in c or 'date' in c),
                df.columns[0]
            )
            df[time_col] = pd.to_datetime(df[time_col])
            df = df.rename(columns={time_col: 'time'}).set_index('time').sort_index()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['close'])
            return df if not df.empty else None

        except Exception as e:
            err_str = str(e).lower()
            # Phát hiện Rate Limit (HTTP 429 hoặc thông báo tiếng Việt/Anh)
            is_rate_limit = ('429' in err_str
                             or 'rate limit' in err_str
                             or 'too many' in err_str
                             or 'giới hạn' in err_str)
            if is_rate_limit and attempt < max_retries - 1:
                wait = wait_times[attempt]
                print(f"  ⏳ Rate limit [{ticker} {resolution}] "
                      f"— chờ {wait}s (lần {attempt+1}/{max_retries})")
                time.sleep(wait)
            else:
                print(f"  [Fetch] {ticker} {resolution}: {e}")
                return None

    return None   # hết số lần thử

# ===========================================================================
# MODULE 2: BỘ LỌC VN-INDEX + RELATIVE STRENGTH
# ===========================================================================
def get_market_regime(start: str, end: str) -> dict:
    """
    Phân tích VN-Index:
    BULL   → Long tự do
    NEUTRAL → Long chọn lọc
    BEAR   → Chỉ Long nếu RS mã > RS_MIN_BEAR, hoặc bắt sóng hồi
    """
    default = {
        'regime': 'NEUTRAL', 'allow_long': True,
        'vnindex_price': 0, 'rsi': 50, 'ma20': 0, 'ma50': 0,
        'vnindex_ret20': 0.0
    }
    df = fetch_ohlcv('VNINDEX', start, end, '1D')
    if df is None or len(df) < 55:
        return default
    try:
        df['ma20'] = ta.sma(df['close'], length=20)
        df['ma50'] = ta.sma(df['close'], length=50)
        df['rsi']  = ta.rsi(df['close'], length=14)
        latest = df.iloc[-1]
        p, m20, m50, rsi = latest['close'], latest['ma20'], latest['ma50'], latest['rsi']

        # Tỷ suất sinh lợi 20 phiên của VN-Index (dùng tính RS)
        ret20 = (p / df['close'].iloc[-RS_LOOKBACK - 1] - 1) if len(df) > RS_LOOKBACK + 1 else 0.0

        if p > m20 and p > m50 and m20 > m50:
            regime, allow = 'BULL', True
        elif p < m20 * 0.95 and p < m50:
            regime, allow = 'BEAR', False   # RS riêng lẻ quyết định sau
        else:
            regime, allow = 'NEUTRAL', True

        return {
            'regime': regime, 'allow_long': allow,
            'vnindex_price': round(p, 2), 'rsi': round(rsi, 1),
            'ma20': round(m20, 2), 'ma50': round(m50, 2),
            'vnindex_ret20': round(ret20, 4)
        }
    except Exception as e:
        print(f"  [Market] {e}")
        return default


def calc_relative_strength(df_stock: pd.DataFrame, vnindex_ret20: float) -> float:
    """
    RS = tỷ suất sinh lợi mã / tỷ suất sinh lợi VN-Index trong 20 phiên.
    RS > 1.0  → mã mạnh hơn thị trường
    RS > 1.05 → đủ điều kiện Long ngay cả khi Bear
    """
    if len(df_stock) < RS_LOOKBACK + 2 or vnindex_ret20 == 0:
        return 1.0
    stock_ret = df_stock['close'].iloc[-1] / df_stock['close'].iloc[-RS_LOOKBACK - 1] - 1
    if abs(vnindex_ret20) < 0.001:
        return 1.0 if stock_ret >= 0 else 0.5
    return round(stock_ret / abs(vnindex_ret20), 3)


# ===========================================================================
# MODULE 3: MCDX BANKER (Bonus Score)
# ===========================================================================
def calc_mcdx_banker(df: pd.DataFrame, length: int = 14) -> float:
    """
    MCDX Banker — đo tỷ lệ mua ròng của dòng tiền lớn.
    Công thức: % khối lượng mua (phiên tăng) / tổng khối lượng trong N phiên.
    Ngưỡng:
      > MCDX_THRESH_1 (55%) → +1 điểm
      > MCDX_THRESH_2 (70%) → +2 điểm (Big Money rõ ràng)
    Ghi chú: Đây là proxy đơn giản của MCDX thực; phản ánh volume-buying pressure.
    """
    if len(df) < length + 2:
        return 50.0
    delta  = df['close'].diff()
    up_vol = df['volume'].where(delta > 0, 0.0)
    rolling_up  = up_vol.rolling(length).sum()
    rolling_tot = df['volume'].rolling(length).sum()
    mcdx = (rolling_up / rolling_tot * 100).replace([np.inf, -np.inf], np.nan).fillna(50)
    return round(float(mcdx.iloc[-1]), 1)


# ===========================================================================
# MODULE 4: FIBONACCI & ICT OTE
# ===========================================================================
def calc_fib(swing_high: float, swing_low: float) -> dict:
    diff = swing_high - swing_low
    fibs = {lvl: swing_high - diff * lvl for lvl in FIB_LEVELS}
    fibs['ote_low']    = swing_high - diff * OTE_HIGH
    fibs['ote_high']   = swing_high - diff * OTE_LOW
    fibs['ext_127']    = swing_low  + diff * TP_EXT_127
    fibs['ext_162']    = swing_low  + diff * TP_EXT_162
    fibs['swing_high'] = swing_high
    fibs['swing_low']  = swing_low
    fibs['midpoint']   = (swing_high + swing_low) / 2
    return fibs


def in_ote_zone(price: float, fibs: dict) -> bool:
    return fibs['ote_low'] <= price <= fibs['ote_high']


def dist_to_ote(price: float, fibs: dict) -> float:
    """Khoảng cách % từ giá hiện tại đến rìa gần nhất của OTE."""
    if price > fibs['ote_high']:
        return (price - fibs['ote_high']) / price
    if price < fibs['ote_low']:
        return (fibs['ote_low'] - price) / price
    return 0.0


def nearest_fib_label(price: float, fibs: dict) -> str:
    labels = {0.236: '23.6%', 0.382: '38.2%', 0.500: '50%',
              0.618: '61.8%', 0.786: '78.6%'}
    closest = min(labels, key=lambda k: abs(price - fibs[k]))
    return labels[closest]


# ===========================================================================
# MODULE 5: ORDER BLOCK (H1) — thay thế H4
# ===========================================================================
def find_bullish_ob(df: pd.DataFrame, lookback: int = 60) -> dict | None:
    """
    Bullish OB trên H1: Nến đỏ cuối cùng ngay trước displacement tăng + BOS xác nhận.
    Tăng lookback lên 60 (H1) để bù cho việc không còn dùng H4.
    Ngưỡng displacement: 0.4% (thay vì 0.6% trên H4) vì biên độ H1 nhỏ hơn.
    """
    s = df.tail(lookback).reset_index(drop=True)
    for i in range(len(s) - 3, 1, -1):
        c, n = s.iloc[i], s.iloc[i + 1]
        if c['close'] >= c['open']:
            continue
        body_n = abs(n['close'] - n['open'])
        if n['close'] <= n['open'] or body_n / max(n['open'], 0.01) < 0.004:
            continue
        recent_high = s.iloc[max(0, i - 3):i]['high'].max()
        if n['high'] > recent_high:
            return {
                'ob_high': round(c['high'], 2),
                'ob_low':  round(c['low'],  2),
                'ob_mid':  round((c['high'] + c['low']) / 2, 2)
            }
    return None


def dist_to_ob(price: float, ob: dict) -> float:
    """Khoảng cách % từ giá đến rìa gần nhất của OB (0 nếu đang trong OB)."""
    if ob['ob_low'] <= price <= ob['ob_high']:
        return 0.0
    if price > ob['ob_high']:
        return (price - ob['ob_high']) / price
    return (ob['ob_low'] - price) / price


# ===========================================================================
# MODULE 6: FAIR VALUE GAP (H1)
# ===========================================================================
def find_bullish_fvg(df: pd.DataFrame, lookback: int = 50) -> list:
    """FVG Bullish trên H1: low[i+1] > high[i-1]."""
    fvgs, current = [], df['close'].iloc[-1]
    s = df.tail(lookback + 2).reset_index(drop=True)
    for i in range(1, len(s) - 1):
        p, n = s.iloc[i - 1], s.iloc[i + 1]
        if n['low'] > p['high']:
            top, bot = n['low'], p['high']
            if current >= bot * 0.97:
                fvgs.append({
                    'fvg_top': round(top, 2),
                    'fvg_bot': round(bot, 2),
                    'fvg_mid': round((top + bot) / 2, 2)
                })
    return fvgs[-3:]


# ===========================================================================
# MODULE 7: BOS / CHoCH (H1)
# ===========================================================================
def detect_structure(df: pd.DataFrame, lookback: int = 40) -> dict:
    """
    BOS Bullish = Higher High xác nhận → uptrend tiếp diễn
    CHoCH Bearish = Lower Low trong uptrend → cảnh báo đảo chiều
    HH-HL = cấu trúc khoẻ mạnh nhất
    """
    s = df.tail(lookback)
    highs, lows = s['high'].values, s['low'].values
    sh, sl = [], []
    for i in range(2, len(highs) - 2):
        if highs[i] == max(highs[i-2:i+3]):
            sh.append(highs[i])
        if lows[i] == min(lows[i-2:i+3]):
            sl.append(lows[i])
    return {
        'bos_bull':   len(sh) >= 2 and sh[-1] > sh[-2],
        'choch_bear': len(sl) >= 2 and sl[-1] < sl[-2],
        'hh_hl':      (len(sh) >= 2 and sh[-1] > sh[-2]) and
                      (len(sl) >= 2 and sl[-1] > sl[-2]),
        'last_sh': sh[-1] if sh else highs.max(),
        'last_sl': sl[-1] if sl else lows.min(),
    }

# ===========================================================================
# MODULE 8: LIQUIDITY SWEEP (M15) — chuyển từ H1 xuống M15
# ===========================================================================
def detect_sweep(df: pd.DataFrame, lookback: int = 24) -> dict:
    """
    Bullish Sweep trên M15: Râu dưới xuyên đáy cũ nhưng đóng cửa lại bên trên.
    Dùng M15 thay H1 để bắt timing entry chính xác hơn.
    lookback=24 ≈ 6 tiếng giao dịch (~ 1.5 phiên).
    """
    s = df.tail(lookback).reset_index(drop=True)
    prev_low = s['low'].iloc[:-3].min()
    last = s.iloc[-1]
    if last['low'] < prev_low and last['close'] > last['open']:
        return {'swept': True, 'type': 'BULL_SWEEP', 'level': round(prev_low, 2)}
    return {'swept': False, 'type': None, 'level': None}


# ===========================================================================
# MODULE 9: VOLUME DRY-UP & SPIKE (H1)
# ===========================================================================
def vol_dryup(df: pd.DataFrame, window: int = 6, threshold: float = 0.65) -> bool:
    """
    Volume cạn dần trong N phiên H1 → phe bán yếu dần.
    window=6 H1 ≈ 1.5 phiên giao dịch VN.
    """
    if len(df) < 25:
        return False
    ma20   = df['volume'].tail(25).mean()
    recent = df['volume'].tail(window).mean()
    return recent < threshold * ma20 and ma20 > 0


def vol_spike(df: pd.DataFrame, mult: float = 1.5) -> bool:
    """Volume nến M15/H1 cuối vượt trội TB → dòng tiền xác nhận."""
    if len(df) < 25:
        return False
    ma20 = df['volume'].tail(25).mean()
    return df['volume'].iloc[-1] > mult * ma20 and ma20 > 0


# ===========================================================================
# MODULE 10: NẾN ĐẢO CHIỀU (M15) — chuyển từ H1 xuống M15
# ===========================================================================
def detect_reversal(df: pd.DataFrame) -> dict:
    """
    Pinbar Bullish và Engulfing Bullish trên M15 (entry timing).
    Ngưỡng thân nến thoải hơn M15 (35% → 40%) vì biên độ nhỏ hơn.
    """
    last, prev = df.iloc[-1], df.iloc[-2]
    body  = abs(last['close'] - last['open'])
    rng   = last['high'] - last['low']
    lower = min(last['close'], last['open']) - last['low']
    result = {'pinbar': False, 'engulfing': False}
    if rng > 0:
        if lower > 0.55 * rng and body < 0.40 * rng and last['close'] > last['open']:
            result['pinbar'] = True
        if (last['close'] > last['open'] and prev['close'] < prev['open']
                and last['close'] > prev['open'] and last['open'] < prev['close']):
            result['engulfing'] = True
    return result


# ===========================================================================
# MODULE 11: TÍNH SL/TP
# ===========================================================================
def calc_trade(price: float, ob: dict | None, fibs: dict, scenario: str) -> dict:
    """
    SL: bám sát cấu trúc (OB, đáy gần nhất), giới hạn tối đa 5%.
    TP: dựa Fibonacci Extension, tối thiểu 10%.
    Hợp lệ khi R:R >= 2.5.
    """
    if scenario == 'UPTREND':
        sl = price * 0.96
        if ob and ob['ob_low'] > price * 0.93:
            sl = max(ob['ob_low'] * 0.99, price * (1 - MAX_SL_PCT))
    else:
        sl = price * 0.97

    sl   = max(sl, price * (1 - MAX_SL_PCT))
    risk = price - sl
    if risk <= 0:
        return {'valid': False}

    tp1 = max(fibs['ext_127'], price + risk * MIN_RR_RATIO)
    tp2 = max(fibs['ext_162'], price + risk * (MIN_RR_RATIO + 1.5))
    tp1 = min(tp1, price * 1.20)
    tp1 = max(tp1, price * (1 + MIN_TP_PCT))

    rr1 = (tp1 - price) / risk
    rr2 = (tp2 - price) / risk

    return {
        'sl':      round(sl,  2),
        'tp1':     round(tp1, 2),
        'tp2':     round(tp2, 2),
        'sl_pct':  round((price - sl)  / price * 100, 1),
        'tp1_pct': round((tp1 - price) / price * 100, 1),
        'tp2_pct': round((tp2 - price) / price * 100, 1),
        'rr1':     round(rr1, 1),
        'rr2':     round(rr2, 1),
        'valid':   rr1 >= MIN_RR_RATIO,
    }


# ===========================================================================
# MODULE 12: PHÂN TÍCH CHÍNH — D1 → H1 → M15
# ===========================================================================
def analyze(ticker: str, start_d1: str, start_h1: str, start_m15: str,
            end: str, market: dict) -> dict | None:
    """
    Trả về dict nếu đạt tiêu chuẩn, None nếu không.
    'approaching' = True nếu mã tiệm cận nhưng chưa đủ điều kiện.
    """
    try:
        # ── Dữ liệu ─────────────────────────────────────────────────────────
        df_d1  = fetch_ohlcv(ticker, start_d1,  end, '1D')
        df_h1  = fetch_ohlcv(ticker, start_h1,  end, '60')
        df_m15 = fetch_ohlcv(ticker, start_m15, end, '15')

        if df_d1 is None or len(df_d1) < 55:
            return None

        # ── Chỉ báo D1 ───────────────────────────────────────────────────────
        df_d1['ma20']  = ta.sma(df_d1['close'], length=20)
        df_d1['ma50']  = ta.sma(df_d1['close'], length=50)
        df_d1['ema21'] = ta.ema(df_d1['close'], length=21)
        bb = ta.bbands(df_d1['close'], length=20)
        df_d1['bb_w'] = (
            (bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1]
            if bb is not None else np.nan
        )
        d = df_d1.iloc[-1]
        if pd.isna(d['ma50']):
            return None

        price  = d['close']
        ma20   = d['ma20']
        ma50   = d['ma50']
        ema21  = d['ema21']

        # ── Xu hướng D1 ──────────────────────────────────────────────────────
        if price > ma20 and price > ma50 and ma20 > ma50:
            trend = 'UPTREND'
        elif price < ma20 and price < ma50 and ma20 < ma50:
            trend = 'DOWNTREND'
        else:
            trend = 'SIDEWAYS'

        # ── Relative Strength vs VN-Index ────────────────────────────────────
        rs = calc_relative_strength(df_d1, market['vnindex_ret20'])

        # Nếu thị trường BEAR: chỉ cho Long nếu RS đủ mạnh
        if not market['allow_long'] and trend == 'UPTREND' and rs < RS_MIN_BEAR:
            return None
        if not market['allow_long'] and trend == 'SIDEWAYS':
            return None

        # ── MCDX Banker (D1, dùng chung toàn bộ phân tích) ──────────────────
        mcdx_d1 = calc_mcdx_banker(df_d1, length=14)

        # ── Phân tích H1 — OB / FVG / Structure / Volume ────────────────────
        ob_h1, fvg_h1 = None, []
        struct_h1 = {'bos_bull': False, 'choch_bear': False, 'hh_hl': False,
                     'last_sh': 0, 'last_sl': 0}
        dry_h1 = False
        rsi_h1 = np.nan
        ema21_h1 = np.nan

        if df_h1 is not None and len(df_h1) >= 30:
            df_h1['rsi']   = ta.rsi(df_h1['close'], length=14)
            df_h1['ema21'] = ta.ema(df_h1['close'], length=21)
            rsi_h1   = df_h1['rsi'].iloc[-1]
            ema21_h1 = df_h1['ema21'].iloc[-1]
            ob_h1    = find_bullish_ob(df_h1, lookback=60)
            fvg_h1   = find_bullish_fvg(df_h1, lookback=50)
            struct_h1 = detect_structure(df_h1, lookback=40)
            dry_h1   = vol_dryup(df_h1, window=6, threshold=0.65)

        # ── Phân tích M15 — Sweep / Reversal / Spike (timing entry) ─────────
        sweep = {'swept': False, 'type': None, 'level': None}
        rev   = {'pinbar': False, 'engulfing': False}
        spike = False

        if df_m15 is not None and len(df_m15) >= 24:
            sweep = detect_sweep(df_m15, lookback=24)
            rev   = detect_reversal(df_m15)
            spike = vol_spike(df_m15, mult=1.5)

        # ── Fibonacci (60 phiên D1) ───────────────────────────────────────────
        sh60  = df_d1['high'].tail(60).max()
        sl60  = df_d1['low'].tail(60).min()
        fibs  = calc_fib(sh60, sl60)
        ote   = in_ote_zone(price, fibs)
        fib_l = nearest_fib_label(price, fibs)
        zone  = "DISCOUNT ✅" if price < fibs['midpoint'] else "PREMIUM ⚠️"

        # ── Khoảng cách đến vùng giá trị (dùng cho Approaching) ─────────────
        d_ote = dist_to_ote(price, fibs)
        d_ob  = dist_to_ob(price, ob_h1) if ob_h1 else 1.0
        near_value = min(d_ote, d_ob)   # % cách vùng gần nhất

        # ── Confluence Scoring ────────────────────────────────────────────────
        score, notes = 0, []

        # Cấu trúc H1
        if struct_h1['hh_hl']:
            score += 2
            notes.append("✅ HH-HL H1 — cấu trúc uptrend lành mạnh")
        elif struct_h1['bos_bull']:
            score += 1
            notes.append("✅ BOS Bullish H1 — Higher High xác nhận")
        if struct_h1['choch_bear']:
            score -= 2
            notes.append("⚠️ CHoCH Bearish H1 — cảnh báo đảo chiều!")

        # Order Block H1
        if ob_h1 and ob_h1['ob_low'] <= price <= ob_h1['ob_high']:
            score += 3
            notes.append(f"📦 Trong OB H1 [{ob_h1['ob_low']} – {ob_h1['ob_high']}]")

        # FVG H1
        for fvg in fvg_h1:
            if fvg['fvg_bot'] <= price <= fvg['fvg_top']:
                score += 2
                notes.append(f"🕳️ Trong FVG H1 [{fvg['fvg_bot']} – {fvg['fvg_top']}]")
                break

        # EMA21 H1
        if not np.isnan(ema21_h1) and ema21_h1 * 0.985 <= price <= ema21_h1 * 1.015:
            score += 1
            notes.append(f"📌 Chạm EMA21 H1 ({ema21_h1:.2f})")

        # ICT OTE (Fibonacci D1)
        if ote:
            score += 2
            notes.append(f"🎯 ICT OTE Fibo {fib_l} — vùng vào lệnh tối ưu")

        # Liquidity Sweep M15
        if sweep['swept'] and sweep['type'] == 'BULL_SWEEP':
            score += 3
            notes.append(f"💧 Liquidity Sweep Bullish M15 tại {sweep['level']}")

        # Nến đảo chiều M15
        if rev['pinbar']:
            score += 2
            notes.append("🕯️ Pinbar Bullish M15")
        if rev['engulfing']:
            score += 2
            notes.append("🕯️ Engulfing Bullish M15")

        # Volume Dry-up H1 (Wyckoff)
        if dry_h1:
            score += 2
            notes.append("📉 Volume Dry-up H1 — cung cạn, Spring sắp nổ")

        # Volume Spike M15
        if spike:
            score += 2
            notes.append("📊 Volume đột biến M15 (≥1.5× TB)")

        # RSI H1
        if not np.isnan(rsi_h1):
            if trend == 'UPTREND' and 32 <= rsi_h1 <= 52:
                score += 1
                notes.append(f"📈 RSI H1 {rsi_h1:.0f} — pullback lý tưởng")
            elif rsi_h1 < 30:
                score += 1
                notes.append(f"📉 RSI H1 {rsi_h1:.0f} — oversold")

        # ── MCDX Banker (Bonus Score) ─────────────────────────────────────────
        mcdx_bonus = 0
        if mcdx_d1 > MCDX_THRESH_2:
            mcdx_bonus = 2
            notes.append(f"💰 MCDX Banker {mcdx_d1:.0f}% — Big Money cực mạnh (+2đ)")
        elif mcdx_d1 > MCDX_THRESH_1:
            mcdx_bonus = 1
            notes.append(f"💰 MCDX Banker {mcdx_d1:.0f}% — Dòng tiền lớn (+1đ)")
        score += mcdx_bonus

        # ── Relative Strength (Bonus) ─────────────────────────────────────────
        if rs > 1.10:
            score += 1
            notes.append(f"💪 RS {rs:.2f} — mã mạnh hơn thị trường rõ rệt (+1đ)")
        elif rs > 1.05 and not market['allow_long']:
            notes.append(f"💪 RS {rs:.2f} — vượt ngưỡng Bear filter")

        # ── Đánh dấu "Tiệm cận" (Approaching) ───────────────────────────────
        # Mã chưa đạt MIN_SMC_SCORE nhưng đang gần vùng giá trị (< 3%)
        is_approaching = (score < MIN_SMC_SCORE and near_value < 0.03
                          and not struct_h1['choch_bear'])

        if score < MIN_SMC_SCORE and not is_approaching:
            return None

        # ── Xây dựng tín hiệu theo kịch bản ─────────────────────────────────
        scenario, signal = None, None

        # KỊ CH BẢN 1: UPTREND PULLBACK
        if trend == 'UPTREND':
            near_ema = not np.isnan(ema21_h1) and ema21_h1 * 0.985 <= price <= ema21_h1 * 1.02
            in_ob    = ob_h1 and ob_h1['ob_low'] <= price
            cond     = near_ema or ote or in_ob

            if cond or is_approaching:
                scenario = 'UPTREND'
                if not is_approaching:
                    t = calc_trade(price, ob_h1, fibs, scenario)
                    if not t['valid']:
                        return None
                    signal = (
                        f"🚀 <b>UPTREND PULLBACK</b>  (T+10~14 ngày)\n"
                        f"   📍 Vùng giá  : {zone}\n"
                        f"   🔍 Fibo gần  : {fib_l}\n"
                        f"   💪 RS vs VNI  : {rs:.2f}{'  🔥' if rs > 1.10 else ''}\n"
                        f"   💵 Vào lệnh  : <b>{price:.2f}</b>\n"
                        f"   🛑 SL        : {t['sl']} (-{t['sl_pct']}%)\n"
                        f"   🎯 TP1       : {t['tp1']} (+{t['tp1_pct']}%)\n"
                        f"   🎯 TP2       : {t['tp2']} (+{t['tp2_pct']}%)\n"
                        f"   ⚖️  R:R      : 1:{t['rr1']} → 1:{t['rr2']}\n"
                        f"   💡 <i>Mua 50% ngay, 50% còn lại khi giá chạm OB/OTE."
                        f" Chốt 50% tại TP1, trailing stop phần còn lại.</i>"
                    )

        # KỊ CH BẢN 2: SIDEWAYS — ĐÁY HỘP
        elif trend == 'SIDEWAYS':
            low20  = df_d1['low'].tail(20).min()
            high20 = df_d1['high'].tail(20).max()
            box_w  = (high20 - low20) / low20
            bb_sq  = not pd.isna(d.get('bb_w', np.nan)) and d['bb_w'] < 0.05
            rsi_os = not np.isnan(rsi_h1) and rsi_h1 < 38

            if price <= low20 * 1.03 and rsi_os and box_w > 0.07:
                scenario = 'SIDEWAYS'
                sl_box  = round(low20 * 0.97, 2)
                tp1_box = round((low20 + high20) / 2, 2)
                tp2_box = round(high20, 2)
                risk_box = price - sl_box
                rr_box   = (tp2_box - price) / risk_box if risk_box > 0 else 0
                if rr_box < MIN_RR_RATIO and not is_approaching:
                    return None
                signal = (
                    f"📦 <b>SIDEWAYS — MUA ĐÁY HỘP</b>  (T+10~14 ngày)\n"
                    f"   📏 Hộp      : {low20:.2f} – {high20:.2f}  ({box_w*100:.1f}%)\n"
                    f"   {'🔒 BB Squeeze — năng lượng tích tụ.' + chr(10) if bb_sq else ''}"
                    f"   📉 RSI H1   : {rsi_h1:.0f}  (oversold)\n"
                    f"   💪 RS vs VNI : {rs:.2f}\n"
                    f"   💵 Vào lệnh : <b>{price:.2f}</b>  (Limit sát đáy)\n"
                    f"   🛑 SL       : {sl_box} (-{((price-sl_box)/price*100):.1f}%)\n"
                    f"   🎯 TP1 (50%): {tp1_box} (+{((tp1_box-price)/price*100):.1f}%)\n"
                    f"   🎯 TP2      : {tp2_box} (+{((tp2_box-price)/price*100):.1f}%)\n"
                    f"   ⚖️  R:R     : 1:{rr_box:.1f}\n"
                    f"   💡 <i>Chốt toàn bộ tại cạnh trên hộp. Không tham.</i>"
                )
            elif is_approaching:
                scenario = 'SIDEWAYS'

        # KỊ CH BẢN 3: DOWNTREND — BẮT SÓNG HỒI
        elif trend == 'DOWNTREND':
            deep   = price < ma20 * 0.88
            rsi_ex = not np.isnan(rsi_h1) and rsi_h1 < 28
            has_sw = sweep['swept'] and sweep['type'] == 'BULL_SWEEP'
            has_rv = rev['pinbar'] or rev['engulfing']

            if deep and rsi_ex and (has_sw or has_rv) and score >= 4:
                scenario = 'DOWNTREND'
                t = calc_trade(price, ob_h1, fibs, scenario)
                if not t['valid']:
                    return None
                disc = (ma20 - price) / ma20 * 100
                signal = (
                    f"🔪 <b>DOWNTREND — BẮT SÓNG HỒI</b>  ⚠️ Rủi ro cao\n"
                    f"   📉 Chiết khấu vs MA20 : {disc:.1f}%\n"
                    f"   📉 RSI H1             : {rsi_h1:.0f}  (cực oversold)\n"
                    f"   💧 Sweep Bullish M15  : {'✅' if has_sw else '—'}\n"
                    f"   🕯️ Nến đảo chiều M15  : {'✅ Pinbar/Engulfing' if has_rv else '—'}\n"
                    f"   💪 RS vs VNI          : {rs:.2f}\n"
                    f"   💵 Vào lệnh           : <b>{price:.2f}</b>  (MAX 25% vốn)\n"
                    f"   🛑 SL                 : {t['sl']} (-{t['sl_pct']}%)\n"
                    f"   🎯 TP1 (EMA21 D1)    : {ema21:.2f} (+{((ema21-price)/price*100):.1f}%)\n"
                    f"   🎯 TP2 (MA20 D1)     : {ma20:.2f} (+{((ma20-price)/price*100):.1f}%)\n"
                    f"   ⚖️  R:R               : 1:{t['rr1']}\n"
                    f"   💡 <i>Bán ngay khi chạm EMA21. NO Margin tuyệt đối.</i>"
                )

        if scenario is None:
            return None

        # Nếu chỉ "tiệm cận" mà chưa có signal → tạo signal đơn giản
        if signal is None and is_approaching:
            ob_str  = f"{ob_h1['ob_low']}–{ob_h1['ob_high']}" if ob_h1 else "—"
            ote_str = f"{fibs['ote_low']:.2f}–{fibs['ote_high']:.2f}"
            near_pct = round(near_value * 100, 1)
            signal = (
                f"⏳ <b>TIỆM CẬN ĐIỀU KIỆN</b>\n"
                f"   Xu hướng D1  : {trend}\n"
                f"   Vùng chờ OB  : {ob_str}\n"
                f"   Vùng chờ OTE : {ote_str}\n"
                f"   Cách vùng    : ~{near_pct:.1f}%\n"
                f"   Score hiện tại: {score}/{MIN_SMC_SCORE} (cần thêm {MIN_SMC_SCORE - score}đ)\n"
                f"   💡 <i>Chưa đủ điều kiện — theo dõi khi giá tiến vào vùng.</i>"
            )

        star  = '⭐' * min(score, 7)
        n_str = "\n   ".join(notes) if notes else "—"

        message = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>{ticker}</b>  ·  {trend}  ·  {star} ({score}đ)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{signal}\n\n"
            f"<i>🧠 SMC/ICT:\n   {n_str}</i>\n\n"
            f"<i>📐 Fibo 60 phiên  H={sh60:.2f} | L={sl60:.2f}\n"
            f"   OTE: {fibs['ote_low']:.2f}–{fibs['ote_high']:.2f}"
            f"  | Ext127: {fibs['ext_127']:.2f}"
            f"  | Ext162: {fibs['ext_162']:.2f}</i>"
        )

        return {
            'ticker':       ticker,
            'scenario':     scenario,
            'score':        score,
            'message':      message,
            'approaching':  is_approaching,
            'near_value':   near_value,
            'rs':           rs,
        }

    except Exception as e:
        print(f"  [Error] {ticker}: {e}")
        return None


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"  VN STOCK SCANNER v4.0")
    print(f"  {now.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*60}\n")

    end       = now.strftime('%Y-%m-%d')
    start_d1  = (now - timedelta(days=200)).strftime('%Y-%m-%d')
    start_h1  = (now - timedelta(days=45)).strftime('%Y-%m-%d')   # 45 ngày H1
    start_m15 = (now - timedelta(days=10)).strftime('%Y-%m-%d')   # 10 ngày M15

    # ── Bước 1: Phân tích thị trường ─────────────────────────────────────────
    print("📊 Phân tích VN-Index...")
    market = get_market_regime(start_d1, end)
    emoji  = {'BULL': '🟢', 'BEAR': '🔴', 'NEUTRAL': '🟡'}.get(market['regime'], '⚪')

    bear_note = ''
    if market['regime'] == 'BEAR':
        bear_note = (
            f"\n   ⚠️ BEAR mode — chỉ Long các mã có RS >{RS_MIN_BEAR} "
            f"(mạnh hơn thị trường)"
        )

    send_telegram(
        f"📊 <b>VN-INDEX — TRẠNG THÁI THỊ TRƯỜNG</b>\n"
        f"   Chỉ số  : {market['vnindex_price']}\n"
        f"   Regime  : {emoji} <b>{market['regime']}</b>\n"
        f"   RSI(14) : {market['rsi']}\n"
        f"   MA20    : {market['ma20']}  |  MA50: {market['ma50']}\n"
        f"   Ret 20p : {market['vnindex_ret20']*100:+.1f}%"
        f"{bear_note}"
    )

    # ── Bước 2: Quét watchlist ────────────────────────────────────────────────
    all_results = []
    for i, ticker in enumerate(WATCHLIST):
        print(f"  [{i+1:3d}/{len(WATCHLIST)}] {ticker}...", end=' ', flush=True)
        res = analyze(ticker, start_d1, start_h1, start_m15, end, market)
        if res:
            tag = "⏳Approaching" if res['approaching'] else f"✅ Score={res['score']}"
            print(tag)
            all_results.append(res)
        else:
            print("—")
        time.sleep(0.5)   # tránh rate-limit

    # ── Bước 3: Phân loại ────────────────────────────────────────────────────
    signals     = [r for r in all_results if not r['approaching']]
    approaching = [r for r in all_results if r['approaching']]

    signals.sort(key=lambda x: x['score'], reverse=True)
    approaching.sort(key=lambda x: x['near_value'])  # gần vùng nhất lên đầu

    top          = signals[:TOP_N_SIGNALS]
    top_approach = approaching[:TOP_N_APPROACHING]

    up   = [r for r in top if r['scenario'] == 'UPTREND']
    sw   = [r for r in top if r['scenario'] == 'SIDEWAYS']
    down = [r for r in top if r['scenario'] == 'DOWNTREND']

    # ── Bước 4: Gửi tóm tắt ──────────────────────────────────────────────────
    send_telegram(
        f"🤖 <b>BÁO CÁO SCANNER v4.0 — {now.strftime('%d/%m/%Y %H:%M')}</b>\n"
        f"🔍 Quét <b>{len(WATCHLIST)}</b> mã\n"
        f"   ✅ Tín hiệu đủ tiêu chuẩn : <b>{len(signals)}</b> mã\n"
        f"   ⏳ Tiệm cận điều kiện     : <b>{len(approaching)}</b> mã\n\n"
        f"🏆 Top {len(top)} mã chính:\n"
        f"   🚀 Uptrend   : {len(up)} mã\n"
        f"   📦 Sideways  : {len(sw)} mã\n"
        f"   🔪 Downtrend : {len(down)} mã\n\n"
        f"<i>⚠️ Công cụ hỗ trợ quyết định — không phải khuyến nghị đầu tư.\n"
        f"SL là bất khả xâm phạm. Quản lý vốn trên hết!</i>"
    )
    time.sleep(1)

    # ── Bước 5: Gửi từng nhóm ────────────────────────────────────────────────
    def send_group(group: list, label: str):
        if not group:
            return
        send_telegram(f"<b>{'─'*22}\n{label}\n{'─'*22}</b>")
        time.sleep(0.5)
        for j in range(0, len(group), 3):
            chunk = group[j:j+3]
            send_telegram("\n\n".join(r['message'] for r in chunk))
            time.sleep(1.5)

    send_group(up,   "🚀 UPTREND — PULLBACK VÀO LỆNH")
    send_group(sw,   "📦 SIDEWAYS — MUA ĐÁY HỘP")
    send_group(down, "🔪 DOWNTREND — BẮT SÓNG HỒI (cực kỳ thận trọng)")

    # ── Bước 6: Gửi Watchlist "Tiệm cận" ─────────────────────────────────────
    if top_approach:
        send_group(top_approach, f"⏳ VÙNG CHỜ — TOP {len(top_approach)} MÃ TIỆM CẬN")
    else:
        send_telegram("⏳ <b>VÙNG CHỜ:</b> Không có mã nào đang tiệm cận điều kiện.")

    # ── Bước 7: Kết thúc ─────────────────────────────────────────────────────
    if not top and not top_approach:
        send_telegram(
            "🤖 <b>SCANNER BÁO CÁO:</b>\n\n"
            "Không có mã nào đạt đủ tiêu chuẩn hôm nay.\n\n"
            "💰 <b>Tiền mặt là vị thế tốt nhất khi thị trường không rõ ràng.</b>"
        )

    print(
        f"\n✅ Xong.\n"
        f"   Tín hiệu: {len(signals)} → gửi top {len(top)}\n"
        f"   Tiệm cận: {len(approaching)} → gửi top {len(top_approach)}\n"
    )


if __name__ == "__main__":
    main()                
            
