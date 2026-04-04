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
from vnstock import vnstock
from datetime import datetime, timedelta


# ===========================================================================
# CẤU HÌNH HỆ THỐNG
# ===========================================================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID')

MIN_RR_RATIO  = 2.5   # R:R tối thiểu mới báo hiệu
MAX_SL_PCT    = 0.05  # SL không sâu hơn 5%
MIN_TP_PCT    = 0.10  # TP tối thiểu 10%
MIN_SMC_SCORE = 3     # Điểm confluence tối thiểu để lọc nhiễu
TOP_N_SIGNALS = 10    # Chỉ gửi Top N mã điểm cao nhất

OTE_LOW    = 0.618    # ICT OTE mức dưới
OTE_HIGH   = 0.786    # ICT OTE mức trên
FIB_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]
TP_EXT_127 = 1.272
TP_EXT_162 = 1.618

WATCHLIST = [
    'SSI', 'VND', 'VCI', 'HCM', 'SHS', 'MBS', 'FTS', 'CTS', 'BSI', 'VIX',
    'HPG', 'HSG', 'NKG', 'VGS', 'SMC', 'TLH',
    'DIG', 'DXG', 'PDR', 'NVL', 'CEO', 'NLG', 'KDH', 'HDG', 'VIC', 'VHM', 'VRE',
    'VCB', 'BID', 'CTG', 'MBB', 'TCB', 'VPB', 'ACB', 'STB', 'SHB', 'TPB', 'HDB', 'VIB',
    'GEX', 'PC1', 'POW', 'REE', 'GEG', 'TV2',
    'FPT', 'MWG', 'PNJ', 'MSN', 'VNM', 'SAB', 'DGW', 'FRT', 'PET',
    'DGC', 'DPM', 'DCM', 'CSV', 'BFC', 'LAS',
    'KBC', 'IDC', 'VGC', 'SZC', 'PHR', 'DPR', 'GVR',
    'PVD', 'PVS', 'BSR', 'OIL', 'PLX', 'GAS', 'PVC',
    'VHC', 'ANV', 'IDI', 'FMC', 'ASM', 'HAH', 'GMD', 'VOS', 'PVT',
    'VGI', 'CTR', 'CMG', 'LCG', 'HHV', 'VCG', 'KSB', 'FCN', 'C4G',
]


# ===========================================================================
# TELEGRAM
# ===========================================================================
def send_telegram(message: str, retries: int = 3):
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
def fetch_ohlcv(ticker: str, start: str, end: str, resolution: str = '1D') -> pd.DataFrame | None:
    try:
        df = stock.stock_historical_data(
            symbol=ticker, start_date=start, end_date=end,
            resolution=resolution, type='stock'
        )
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        time_col = next((c for c in df.columns if 'time' in c or 'date' in c), df.columns[0])
        df[time_col] = pd.to_datetime(df[time_col])
        df = df.rename(columns={time_col: 'time'}).set_index('time').sort_index()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close'])
        return df
    except Exception as e:
        print(f"  [Fetch] {ticker} {resolution}: {e}")
        return None


def resample_to_h4(df_h1: pd.DataFrame) -> pd.DataFrame:
    """Resample H1 → H4 (thị trường VN mở 2 phiên/ngày nên 4H là hợp lý)."""
    df_h4 = df_h1.resample('4h').agg(
        open=('open', 'first'), high=('high', 'max'),
        low=('low', 'min'), close=('close', 'last'), volume=('volume', 'sum')
    ).dropna(subset=['open', 'close'])
    return df_h4


# ===========================================================================
# MODULE 2: BỘ LỌC VN-INDEX
# ===========================================================================
def get_market_regime(start: str, end: str) -> dict:
    """
    Phân tích VN-Index để xác định thời tiết thị trường.
    BULL  → cho phép đánh cả 3 kịch bản
    BEAR  → chỉ cho bắt sóng hồi (kịch bản 3), cực kỳ chọn lọc
    NEUTRAL → cẩn thận, ưu tiên Sideways và Uptrend chất lượng cao
    """
    default = {'regime': 'NEUTRAL', 'allow_long': True,
                'vnindex_price': 0, 'rsi': 50, 'ma20': 0, 'ma50': 0}
    df = fetch_ohlcv('VNINDEX', start, end, '1D')
    if df is None or len(df) < 55:
        return default
    try:
        df['ma20'] = ta.sma(df['close'], length=20)
        df['ma50'] = ta.sma(df['close'], length=50)
        df['rsi']  = ta.rsi(df['close'], length=14)
        latest = df.iloc[-1]
        p, m20, m50, rsi = latest['close'], latest['ma20'], latest['ma50'], latest['rsi']

        if p > m20 and p > m50 and m20 > m50:
            regime, allow = 'BULL', True
        elif p < m20 * 0.95 and p < m50:
            regime, allow = 'BEAR', False
        else:
            regime, allow = 'NEUTRAL', True

        return {'regime': regime, 'allow_long': allow,
                'vnindex_price': round(p, 2), 'rsi': round(rsi, 1),
                'ma20': round(m20, 2), 'ma50': round(m50, 2)}
    except Exception as e:
        print(f"  [Market] {e}")
        return default


# ===========================================================================
# MODULE 3: FIBONACCI & ICT OTE
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


def nearest_fib_label(price: float, fibs: dict) -> str:
    labels = {0.236: '23.6%', 0.382: '38.2%', 0.500: '50%',
              0.618: '61.8%', 0.786: '78.6%'}
    return min(labels, key=lambda k: abs(price - fibs[k]))
    return labels[min(labels, key=lambda k: abs(price - fibs[k]))]


# ===========================================================================
# MODULE 4: ORDER BLOCK (H4)
# ===========================================================================
def find_bullish_ob(df: pd.DataFrame, lookback: int = 60) -> dict | None:
    """
    Bullish OB: Nến đỏ cuối cùng ngay trước displacement tăng + BOS xác nhận.
    Logic: Smart Money mua tại nến đỏ này → khi giá quay lại là vùng vàng.
    """
    s = df.tail(lookback).reset_index(drop=True)
    for i in range(len(s) - 3, 1, -1):
        c, n = s.iloc[i], s.iloc[i + 1]
        if c['close'] >= c['open']:
            continue
        body_n = abs(n['close'] - n['open'])
        if n['close'] <= n['open'] or body_n / max(n['open'], 0.01) < 0.006:
            continue
        recent_high = s.iloc[max(0, i - 3):i]['high'].max()
        if n['high'] > recent_high:
            return {'ob_high': round(c['high'], 2),
                    'ob_low':  round(c['low'],  2),
                    'ob_mid':  round((c['high'] + c['low']) / 2, 2)}
    return None


# ===========================================================================
# MODULE 5: FAIR VALUE GAP (H4)
# ===========================================================================
def find_bullish_fvg(df: pd.DataFrame, lookback: int = 40) -> list:
    """FVG Bullish: low[i+1] > high[i-1] — khoảng trống cung cầu chưa fill."""
    fvgs, current = [], df['close'].iloc[-1]
    s = df.tail(lookback + 2).reset_index(drop=True)
    for i in range(1, len(s) - 1):
        p, n = s.iloc[i - 1], s.iloc[i + 1]
        if n['low'] > p['high']:
            top, bot = n['low'], p['high']
            if current >= bot * 0.97:
                fvgs.append({'fvg_top': round(top, 2),
                             'fvg_bot': round(bot, 2),
                             'fvg_mid': round((top + bot) / 2, 2)})
    return fvgs[-3:]


# ===========================================================================
# MODULE 6: BOS / CHoCH (H4)
# ===========================================================================
def detect_structure(df: pd.DataFrame, lookback: int = 35) -> dict:
    """
    BOS (Break of Structure) = đỉnh sau > đỉnh trước → uptrend tiếp diễn
    CHoCH (Change of Character) = đáy sau < đáy trước trong uptrend → cảnh báo đảo chiều
    HH-HL = Higher High + Higher Low → cấu trúc lành mạnh nhất
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
# MODULE 7: LIQUIDITY SWEEP (H1)
# ===========================================================================
def detect_sweep(df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    Bullish Sweep: Râu dưới xuyên đáy cũ nhưng đóng cửa lại bên trên →
    Smart Money quét SL của phe Short, sau đó đảo lên.
    Đây là tín hiệu entry cực mạnh trong ICT.
    """
    s = df.tail(lookback).reset_index(drop=True)
    prev_low = s['low'].iloc[:-3].min()
    last = s.iloc[-1]
    if last['low'] < prev_low and last['close'] > last['open']:
        return {'swept': True, 'type': 'BULL_SWEEP', 'level': round(prev_low, 2)}
    return {'swept': False, 'type': None, 'level': None}


# ===========================================================================
# MODULE 8: VOLUME DRY-UP & SPIKE
# ===========================================================================
def vol_dryup(df: pd.DataFrame, window: int = 5, threshold: float = 0.65) -> bool:
    """
    Volume đang cạn dần trong N phiên pullback → phe bán không còn áp lực.
    Wyckoff gọi đây là "No Supply" — tiền đề của Spring bùng nổ.
    """
    if len(df) < 25:
        return False
    ma20 = df['volume'].tail(25).mean()
    recent = df['volume'].tail(window).mean()
    return recent < threshold * ma20 and ma20 > 0


def vol_spike(df: pd.DataFrame, mult: float = 1.5) -> bool:
    """Volume nến hiện tại vượt trội TB → xác nhận có dòng tiền vào."""
    if len(df) < 25:
        return False
    ma20 = df['volume'].tail(25).mean()
    return df['volume'].iloc[-1] > mult * ma20 and ma20 > 0


# ===========================================================================
# MODULE 9: NẾN ĐẢO CHIỀU (H1)
# ===========================================================================
def detect_reversal(df: pd.DataFrame) -> dict:
    """Pinbar Bullish và Engulfing Bullish tại nến H1 mới nhất."""
    last, prev = df.iloc[-1], df.iloc[-2]
    body  = abs(last['close'] - last['open'])
    rng   = last['high'] - last['low']
    lower = min(last['close'], last['open']) - last['low']
    result = {'pinbar': False, 'engulfing': False}
    if rng > 0:
        if lower > 0.60 * rng and body < 0.35 * rng and last['close'] > last['open']:
            result['pinbar'] = True
        if (last['close'] > last['open'] and prev['close'] < prev['open']
                and last['close'] > prev['open'] and last['open'] < prev['close']):
            result['engulfing'] = True
    return result


# ===========================================================================
# MODULE 10: TÍNH SL/TP (T+10-14 ngày)
# ===========================================================================
def calc_trade(price: float, ob: dict | None, fibs: dict, scenario: str) -> dict:
    """
    SL: đặt sát cấu trúc (OB, đáy hộp, đáy gần nhất), không sâu hơn 5%.
    TP: dựa vào Fibonacci Extension, tối thiểu 10%.
    Chỉ hợp lệ nếu R:R >= 2.5.
    """
    if scenario == 'UPTREND':
        sl = price * 0.96
        if ob and ob['ob_low'] > price * 0.93:
            sl = max(ob['ob_low'] * 0.99, price * (1 - MAX_SL_PCT))
    elif scenario == 'SIDEWAYS':
        sl = price * 0.97
    else:
        sl = price * 0.97

    sl   = max(sl, price * (1 - MAX_SL_PCT))
    risk = price - sl

    tp1 = fibs['ext_127']
    tp2 = fibs['ext_162']

    if tp1 < price + risk * MIN_RR_RATIO:
        tp1 = price + risk * MIN_RR_RATIO
    if tp2 < tp1 * 1.03:
        tp2 = price + risk * (MIN_RR_RATIO + 1.5)

    tp1 = min(tp1, price * 1.20)
    tp1 = max(tp1, price * (1 + MIN_TP_PCT))

    rr1 = (tp1 - price) / risk if risk > 0 else 0
    rr2 = (tp2 - price) / risk if risk > 0 else 0

    return {
        'sl': round(sl, 2), 'tp1': round(tp1, 2), 'tp2': round(tp2, 2),
        'sl_pct':  round((price - sl)  / price * 100, 1),
        'tp1_pct': round((tp1 - price) / price * 100, 1),
        'tp2_pct': round((tp2 - price) / price * 100, 1),
        'rr1': round(rr1, 1), 'rr2': round(rr2, 1),
        'valid': rr1 >= MIN_RR_RATIO,
    }


# ===========================================================================
# MODULE 11: PHÂN TÍCH CHÍNH — D1 → H4 → H1
# ===========================================================================
def analyze(ticker: str, start_d1: str, start_h1: str, end: str,
            market: dict) -> dict | None:
    try:
        # ── Lấy dữ liệu ──────────────────────────────────────────────────────
        df_d1 = fetch_ohlcv(ticker, start_d1, end, '1D')
        df_h1 = fetch_ohlcv(ticker, start_h1, end, '60')
        if df_d1 is None or len(df_d1) < 55:
            return None

        # ── Chỉ báo D1 ───────────────────────────────────────────────────────
        df_d1['ma20']  = ta.sma(df_d1['close'], length=20)
        df_d1['ma50']  = ta.sma(df_d1['close'], length=50)
        df_d1['ema21'] = ta.ema(df_d1['close'], length=21)
        df_d1['vol20'] = ta.sma(df_d1['volume'], length=20)
        bb = ta.bbands(df_d1['close'], length=20)
        df_d1['bb_w'] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1] if bb is not None else np.nan
        d = df_d1.iloc[-1]
        if pd.isna(d['ma50']):
            return None

        price = d['close']
        ma20, ma50, ema21_d1 = d['ma20'], d['ma50'], d['ema21']

        # ── Xu hướng D1 ──────────────────────────────────────────────────────
        if price > ma20 and price > ma50 and ma20 > ma50:
            trend = 'UPTREND'
        elif price < ma20 and price < ma50 and ma20 < ma50:
            trend = 'DOWNTREND'
        else:
            trend = 'SIDEWAYS'

        if not market['allow_long'] and trend == 'UPTREND':
            return None   # Thị trường BEAR → không đánh thuận

        # ── Khung H4 (resample H1) ───────────────────────────────────────────
        ob_h4, fvg_h4, struct_h4 = None, [], {'bos_bull': False, 'choch_bear': False, 'hh_hl': False, 'last_sh': 0, 'last_sl': 0}
        ema21_h4 = None
        dry_h4   = False
        df_h4    = None

        if df_h1 is not None and len(df_h1) >= 30:
            df_h4 = resample_to_h4(df_h1)
            if len(df_h4) >= 20:
                df_h4['ema21'] = ta.ema(df_h4['close'], length=21)
                ema21_h4 = df_h4['ema21'].iloc[-1]
                ob_h4    = find_bullish_ob(df_h4)
                fvg_h4   = find_bullish_fvg(df_h4)
                struct_h4 = detect_structure(df_h4)
                dry_h4   = vol_dryup(df_h4, window=5, threshold=0.65)

        # ── Khung H1 ─────────────────────────────────────────────────────────
        rsi_h1 = np.nan
        sweep  = {'swept': False, 'type': None, 'level': None}
        rev    = {'pinbar': False, 'engulfing': False}
        spike  = False

        if df_h1 is not None and len(df_h1) >= 20:
            df_h1['rsi'] = ta.rsi(df_h1['close'], length=14)
            rsi_h1 = df_h1['rsi'].iloc[-1]
            sweep  = detect_sweep(df_h1)
            rev    = detect_reversal(df_h1)
            spike  = vol_spike(df_h1, mult=1.5)

        # ── Fibonacci (60 phiên D1) ───────────────────────────────────────────
        sh60  = df_d1['high'].tail(60).max()
        sl60  = df_d1['low'].tail(60).min()
        fibs  = calc_fib(sh60, sl60)
        ote   = in_ote_zone(price, fibs)
        fib_l = nearest_fib_label(price, fibs)
        zone  = "DISCOUNT ✅" if price < fibs['midpoint'] else "PREMIUM ⚠️"

        # ── Confluence Scoring ────────────────────────────────────────────────
        score, notes = 0, []

        # Cấu trúc H4 (quan trọng nhất)
        if struct_h4['hh_hl']:
            score += 2
            notes.append("✅ HH-HL H4 — cấu trúc uptrend lành mạnh")
        elif struct_h4['bos_bull']:
            score += 1
            notes.append("✅ BOS Bullish H4 — Higher High xác nhận")
        if struct_h4['choch_bear']:
            score -= 2
            notes.append("⚠️ CHoCH Bearish H4 — cảnh báo đảo chiều!")

        # Order Block H4
        if ob_h4 and ob_h4['ob_low'] <= price <= ob_h4['ob_high']:
            score += 3
            notes.append(f"📦 Trong OB H4 [{ob_h4['ob_low']} – {ob_h4['ob_high']}]")

        # FVG H4
        for fvg in fvg_h4:
            if fvg['fvg_bot'] <= price <= fvg['fvg_top']:
                score += 2
                notes.append(f"🕳️ Trong FVG H4 [{fvg['fvg_bot']} – {fvg['fvg_top']}]")
                break

        # EMA21 H4
        if ema21_h4 and ema21_h4 * 0.985 <= price <= ema21_h4 * 1.015:
            score += 1
            notes.append(f"📌 Chạm EMA21 H4 ({ema21_h4:.2f}) — vùng chờ chuẩn")

        # ICT OTE
        if ote:
            score += 2
            notes.append(f"🎯 ICT OTE Zone Fibo {fib_l} — vùng vào lệnh tối ưu")

        # Sweep H1 — tín hiệu entry mạnh nhất
        if sweep['swept'] and sweep['type'] == 'BULL_SWEEP':
            score += 3
            notes.append(f"💧 Liquidity Sweep Bullish H1 tại {sweep['level']}")

        # Nến đảo chiều H1
        if rev['pinbar']:
            score += 2
            notes.append("🕯️ Pinbar Bullish H1")
        if rev['engulfing']:
            score += 2
            notes.append("🕯️ Engulfing Bullish H1")

        # Volume Dry-up H4 (Wyckoff)
        if dry_h4:
            score += 2
            notes.append("📉 Volume Dry-up H4 — cung cạn, Spring sắp nổ")

        # Volume Spike H1
        if spike:
            score += 2
            notes.append("📊 Volume đột biến H1 (≥1.5× TB)")

        # RSI H1
        if not np.isnan(rsi_h1):
            if trend == 'UPTREND' and 32 <= rsi_h1 <= 52:
                score += 1
                notes.append(f"📈 RSI H1 {rsi_h1:.0f} — vùng pullback lý tưởng")
            elif rsi_h1 < 30:
                score += 1
                notes.append(f"📉 RSI H1 {rsi_h1:.0f} — oversold")

        if score < MIN_SMC_SCORE:
            return None

        # ── Xây dựng tín hiệu theo kịch bản ─────────────────────────────────
        scenario, signal = None, None

        # ── KỊ CH BẢN 1: UPTREND PULLBACK ────────────────────────────────────
        if trend == 'UPTREND':
            near_ema = ema21_h4 and ema21_h4 * 0.985 <= price <= ema21_h4 * 1.02
            in_ob    = ob_h4 and ob_h4['ob_low'] <= price
            cond     = near_ema or ote or in_ob

            if cond:
                scenario = 'UPTREND'
                t = calc_trade(price, ob_h4, fibs, scenario)
                if not t['valid']:
                    return None
                entry_note = (
                    "Mua 50% ngay, 50% còn lại nếu giá về sâu hơn vào OTE/OB. "
                    "Chốt 50% tại TP1, trailing stop phần còn lại đến TP2."
                )
                signal = (
                    f"🚀 <b>UPTREND PULLBACK</b>  (T+10~14 ngày)\n"
                    f"   📍 Vùng giá  : {zone}\n"
                    f"   🔍 Fibo gần  : {fib_l}\n"
                    f"   💵 Vào lệnh  : <b>{price:.2f}</b>\n"
                    f"   🛑 SL        : {t['sl']} (-{t['sl_pct']}%)\n"
                    f"   🎯 TP1       : {t['tp1']} (+{t['tp1_pct']}%)\n"
                    f"   🎯 TP2       : {t['tp2']} (+{t['tp2_pct']}%)\n"
                    f"   ⚖️  R:R      : 1:{t['rr1']} → 1:{t['rr2']}\n"
                    f"   💡 <i>{entry_note}</i>"
                )

        # ── KỊ CH BẢN 2: SIDEWAYS — ĐÁY HỘP ─────────────────────────────────
        elif trend == 'SIDEWAYS':
            low20  = df_d1['low'].tail(20).min()
            high20 = df_d1['high'].tail(20).max()
            box_w  = (high20 - low20) / low20
            bb_sq  = not pd.isna(d.get('bb_w', np.nan)) and d['bb_w'] < 0.05
            rsi_os = not np.isnan(rsi_h1) and rsi_h1 < 38

            if price <= low20 * 1.03 and rsi_os and box_w > 0.07:
                scenario = 'SIDEWAYS'
                fibs_box = calc_fib(high20, low20)
                sl_box   = round(low20 * 0.97, 2)
                tp1_box  = round((low20 + high20) / 2, 2)
                tp2_box  = round(high20, 2)
                risk_box = price - sl_box
                rr_box   = (tp2_box - price) / risk_box if risk_box > 0 else 0
                if rr_box < MIN_RR_RATIO:
                    return None

                signal = (
                    f"📦 <b>SIDEWAYS — MUA ĐÁY HỘP</b>  (T+10~14 ngày)\n"
                    f"   📏 Hộp      : {low20:.2f} – {high20:.2f}  ({box_w*100:.1f}%)\n"
                    f"   {'🔒 BB Squeeze! Năng lượng đang tích tụ.' + chr(10) if bb_sq else ''}"
                    f"   📉 RSI H1   : {rsi_h1:.0f} (oversold)\n"
                    f"   💵 Vào lệnh : <b>{price:.2f}</b>  (kê Limit sát đáy)\n"
                    f"   🛑 SL       : {sl_box} (-{((price-sl_box)/price*100):.1f}%)  thủng đáy → thoát ngay\n"
                    f"   🎯 TP1 (50%): {tp1_box} (+{((tp1_box-price)/price*100):.1f}%)\n"
                    f"   🎯 TP2 (100%): {tp2_box} (+{((tp2_box-price)/price*100):.1f}%)\n"
                    f"   ⚖️  R:R     : 1:{rr_box:.1f}\n"
                    f"   💡 <i>Chốt toàn bộ tại cạnh trên hộp. Không tham.</i>"
                )

        # ── KỊ CH BẢN 3: DOWNTREND — BẮT SÓNG HỒI ───────────────────────────
        elif trend == 'DOWNTREND':
            deep   = price < ma20 * 0.88
            rsi_ex = not np.isnan(rsi_h1) and rsi_h1 < 28
            has_sw = sweep['swept'] and sweep['type'] == 'BULL_SWEEP'
            has_rv = rev['pinbar'] or rev['engulfing']

            if deep and rsi_ex and (has_sw or has_rv) and score >= 4:
                scenario = 'DOWNTREND'
                t = calc_trade(price, ob_h4, fibs, scenario)
                if not t['valid']:
                    return None
                disc = (ma20 - price) / ma20 * 100

                signal = (
                    f"🔪 <b>DOWNTREND — BẮT SÓNG HỒI</b>  ⚠️ Rủi ro cao\n"
                    f"   📉 Chiết khấu vs MA20 : {disc:.1f}%\n"
                    f"   📉 RSI H1             : {rsi_h1:.0f}  (cực oversold)\n"
                    f"   💧 Sweep Bullish       : {'✅ Có' if has_sw else '—'}\n"
                    f"   🕯️ Nến đảo chiều       : {'✅ Pinbar/Engulfing' if has_rv else '—'}\n"
                    f"   💵 Vào lệnh            : <b>{price:.2f}</b>  (MAX 25% vốn, NO Margin)\n"
                    f"   🛑 SL                  : {t['sl']} (-{t['sl_pct']}%)  — CỨNG NHẮC TUYỆT ĐỐI\n"
                    f"   🎯 TP1 (EMA21)        : {ema21_d1:.2f} (+{((ema21_d1-price)/price*100):.1f}%)\n"
                    f"   🎯 TP2 (MA20)         : {ma20:.2f} (+{((ma20-price)/price*100):.1f}%)\n"
                    f"   ⚖️  R:R                : 1:{t['rr1']}\n"
                    f"   💡 <i>Bán ngay khi chạm EMA21 hoặc MA20. Không giữ qua đêm nếu bị giảm >2%.</i>"
                )

        if signal is None or scenario is None:
            return None

        star  = '⭐' * min(score, 7)
        n_str = "\n   ".join(notes) if notes else "—"

        message = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>{ticker}</b>  ·  {trend}  ·  {star} ({score}đ)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{signal}\n\n"
            f"<i>🧠 SMC/ICT:\n   {n_str}</i>\n\n"
            f"<i>📐 Fibo 60 phiên  H={sh60:.2f} | L={sl60:.2f}\n"
            f"   OTE: {fibs['ote_low']:.2f}–{fibs['ote_high']:.2f}  "
            f"| Ext1: {fibs['ext_127']:.2f}  | Ext2: {fibs['ext_162']:.2f}</i>"
        )

        return {'ticker': ticker, 'scenario': scenario, 'score': score, 'message': message}

    except Exception as e:
        print(f"  [Error] {ticker}: {e}")
        return None


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"  VN STOCK SCANNER v3.0")
    print(f"  {now.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*60}\n")

    end      = now.strftime('%Y-%m-%d')
    start_d1 = (now - timedelta(days=200)).strftime('%Y-%m-%d')
    start_h1 = (now - timedelta(days=30)).strftime('%Y-%m-%d')

    # Bước 1: Thị trường tổng
    print("📊 Phân tích VN-Index...")
    market = get_market_regime(start_d1, end)
    emoji  = {'BULL': '🟢', 'BEAR': '🔴', 'NEUTRAL': '🟡'}.get(market['regime'], '⚪')
    send_telegram(
        f"📊 <b>VN-INDEX — TRẠNG THÁI THỊ TRƯỜNG</b>\n"
        f"   Chỉ số  : {market['vnindex_price']}\n"
        f"   Regime  : {emoji} <b>{market['regime']}</b>\n"
        f"   RSI(14) : {market['rsi']}\n"
        f"   MA20    : {market['ma20']}  |  MA50: {market['ma50']}\n"
        f"   {'✅ Cho phép đánh thuận xu hướng' if market['allow_long'] else '🚫 Thị trường BEAR — Chỉ bắt sóng hồi, cực kỳ chọn lọc!'}"
    )

    # Bước 2: Quét watchlist
    results = []
    for i, ticker in enumerate(WATCHLIST):
        print(f"  [{i+1:3d}/{len(WATCHLIST)}] {ticker}...", end=' ', flush=True)
        res = analyze(ticker, start_d1, start_h1, end, market)
        if res:
            print(f"✅ Score={res['score']}")
            results.append(res)
        else:
            print("—")
        time.sleep(0.4)

    # Bước 3: Rank → Top N
    results.sort(key=lambda x: x['score'], reverse=True)
    top = results[:TOP_N_SIGNALS]

    up   = [r for r in top if r['scenario'] == 'UPTREND']
    sw   = [r for r in top if r['scenario'] == 'SIDEWAYS']
    down = [r for r in top if r['scenario'] == 'DOWNTREND']

    # Bước 4: Gửi tóm tắt
    send_telegram(
        f"🤖 <b>BÁO CÁO SCANNER — {now.strftime('%d/%m/%Y %H:%M')}</b>\n"
        f"🔍 Quét <b>{len(WATCHLIST)}</b> mã  →  <b>{len(results)}</b> tín hiệu đủ tiêu chuẩn\n"
        f"🏆 Top <b>{len(top)}</b> mã điểm cao nhất:\n\n"
        f"   🚀 Uptrend   : {len(up)} mã\n"
        f"   📦 Sideways  : {len(sw)} mã\n"
        f"   🔪 Downtrend : {len(down)} mã\n\n"
        f"<i>⚠️ Công cụ hỗ trợ quyết định — không phải khuyến nghị đầu tư.\n"
        f"SL là bất khả xâm phạm. Quản lý vốn trên hết!</i>"
    )
    time.sleep(1)

    # Bước 5: Gửi từng nhóm (3 mã/tin)
    def send_group(group: list, label: str):
        if not group:
            return
        send_telegram(f"<b>{'─'*22}\n{label}\n{'─'*22}</b>")
        time.sleep(0.5)
        for j in range(0, len(group), 3):
            chunk = group[j:j+3]
            send_telegram("\n\n".join(r['message'] for r in chunk))
            time.sleep(1.5)

    send_group(up,   "🚀 UPTREND — PULLBACK VÀ VÀO LỆNH")
    send_group(sw,   "📦 SIDEWAYS — MUA ĐÁY HỘP")
    send_group(down, "🔪 DOWNTREND — BẮT SÓNG HỒI (cực kỳ thận trọng)")

    if not top:
        send_telegram(
            "🤖 <b>SCANNER BÁO CÁO:</b>\n\n"
            "Không có mã nào đạt đủ tiêu chuẩn hôm nay.\n\n"
            "💰 <b>Tiền mặt là vị thế tốt nhất khi thị trường không rõ ràng.</b>"
        )

    print(f"\n✅ Xong. Tìm {len(results)} tín hiệu → gửi top {len(top)} mã.\n")


if __name__ == "__main__":
    main()
