import os
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
# Cách import này sẽ giúp bot tự thích nghi với mọi phiên bản vnstock
import vnstock
def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def get_data(symbol):
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')
    try:
        # Gọi thẳng hàm stock_historical_data
        df = stock_historical_data(symbol, start_date, end_date, "1D", "stock")
        return df
    except: 
        return None

def analyze(ticker):
    df = get_data(ticker)
    if df is None or len(df) < 50: return None
# 2. WATCHLIST 150 MÃ & DỮ LIỆU THỊ TRƯỜNG
# ==========================================
def get_comprehensive_watch_list():
    try:
        vn100 = index_components("VN100")
        high_liquidity_others = [
            'ACV', 'VGI', 'MCH', 'FOX', 'VTP', 'BGI', 'VGS', 'IDC', 'TNG', 'PVS', 
            'PVS', 'PVC', 'PVB', 'IDP', 'MML', 'DDV', 'BSR', 'OIL', 'C4G', 'HHV',
            'VEA', 'MHT', 'ABB', 'NAB', 'KLB', 'BVB', 'SGB', 'TCI', 'AAS', 'VFS', 
            'DSC', 'TVS', 'VUA', 'TIP', 'D2D', 'SZC', 'NTC', 'SIP', 'GVR', 'PHR'
        ]
        return list(set(vn100 + high_liquidity_others))[:150]
    except:
        return ['SSI', 'VND', 'HPG', 'DIG', 'GEX', 'VCI', 'PVD']

def get_market_index():
    # Lấy dữ liệu VNINDEX để làm tham chiếu RS
    return stock_historical_data("VNINDEX", "2025-08-01", "2026-03-29", "1D", "index")

# ==========================================
# 3. CÁC MODULE THUẬT TOÁN ĐỊNH LƯỢNG
# ==========================================

# --- THUẬT TOÁN 1: MCDX PRO ---
def calculate_mcdx_pro(df):
    rsi = ta.rsi(df['close'], length=10)
    df['mcdx_red'] = (rsi - 35).clip(lower=0) * 2.8 # Banker
    df['mcdx_green'] = (75 - rsi).clip(lower=0) * 1.6 # Retail
    df['mcdx_yellow'] = (100 - df['mcdx_red'] - df['mcdx_green']).clip(lower=0)
    return df

# --- THUẬT TOÁN 2: VSA & POCKET PIVOT ---
def detect_vsa_and_pocket(df):
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    vol_avg20 = df['volume'].rolling(20).mean().iloc[-1]
    signals = []
    
    # SOS & Pocket Pivot
    is_pocket = (curr['close'] > prev['close']) and (curr['volume'] > df['volume'].shift(1).rolling(10).max().iloc[-1])
    if curr['close'] > prev['close'] * 1.03 and curr['volume'] > 1.5 * vol_avg20:
        signals.append("🚀 SOS: Dòng tiền bùng nổ")
    if is_pocket:
        signals.append("🎯 Pocket Pivot: Điểm nổ trong nền")
    
    # Spring/No Supply
    if curr['low'] < prev['low'] and curr['close'] > prev['close'] and curr['volume'] > vol_avg20:
        signals.append("🌪️ Shakeout: Rũ bỏ thành công")
    
    return signals, is_pocket

# --- THUẬT TOÁN 3: VCP & RS LINE ---
def calculate_vcp_rs(df, index_df):
    # RS Line (Relative Strength)
    df['rs_line'] = (df['close'] / df['close'].shift(10)) / (index_df['close'] / index_df['close'].shift(10))
    rs_status = "MẠNH" if df['rs_line'].iloc[-1] > 1 else "YẾU"
    
    # VCP (Volatility Contraction)
    df['range'] = (df['high'] - df['low']) / df['close']
    is_tight = df['range'].rolling(5).mean().iloc[-1] < df['range'].rolling(20).mean().iloc[-1] * 0.8
    
    return rs_status, is_tight

# --- THUẬT TOÁN 4: PIVOT POINT TARGET ---
def calculate_pivot_targets(df):
    # Tính dựa trên High/Low/Close phiên trước
    p = (df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 3
    r1 = round(2*p - df['low'].shift(1), 1)
    r2 = round(p + (df['high'].shift(1) - df['low'].shift(1)), 1)
    r3 = round(df['high'].shift(1) + 2*(p - df['low'].shift(1)), 1)
    s1 = round(2*p - df['high'].shift(1), 1)
    return r1, r2, r3, s1

# ==========================================
# 4. ENGINE PHÂN TÍCH TỔNG HỢP
# ==========================================
def analyze_ultimate_stock(ticker, index_df):
    try:
        # 1. Dữ liệu cơ bản & Tài chính
        ls_df = listing_companies()
        info = ls_df[ls_df['ticker'] == ticker].iloc[0]
        fin = financial_flow(ticker, 'quarter', 'near_4_quarters').iloc[-1]
        
        # 2. Dữ liệu kỹ thuật
        df = stock_historical_data(ticker, "2025-08-01", "2026-03-29", "1D", "stock")
        df.ta.ema(length=21, append=True)
        df = calculate_mcdx_pro(df)
        
        # 3. Gọi các module thuật toán
        vsa_sigs, is_pocket = detect_vsa_and_pocket(df)
        rs_status, is_tight = calculate_vcp_rs(df, index_df)
        r1, r2, r3, s1 = calculate_pivot_targets(df)
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 4. Chấm điểm hệ thống (Max 10)
        score = 0
        if curr['close'] > curr['EMA_21']: score += 2
        if curr['mcdx_red'] > 50: score += 3
        if rs_status == "MẠNH": score += 2
        if is_tight: score += 1
        if is_pocket: score += 2

        return {
            "ticker": ticker, "name": info['organ_name'], "price": curr['close'],
            "change": round(((curr['close']-prev['close'])/prev['close'])*100, 2),
            "cap": round(fin.get('market_cap', 0)/1e12, 1), "shares": round(fin.get('equity', 0)/1e12*10, 0),
            "mcdx_r": round(curr['mcdx_red'], 1), "mcdx_y": round(curr['mcdx_yellow'], 1),
            "rs": rs_status, "tight": is_tight, "vsa": vsa_sigs, "score": score,
            "r1": r1, "r2": r2, "r3": r3, "s1": s1, "vol": curr['volume']
        }
    except: return None

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    watch_list = get_comprehensive_watch_list()
    index_df = get_market_index()
    final_list = []

    print(f"[{datetime.now().strftime('%H:%M')}] Đang quét 150 mã với ENGINE SIÊU CẤP...")
    
    for ticker in watch_list:
        data = analyze_ultimate_stock(ticker, index_df)
        if data: final_list.append(data)

    # 1. BÁO CÁO TOP 5
    top_5 = sorted(final_list, key=lambda x: x['score'], reverse=True)[:5]
    header = "🚨 **THE QUANT T+ ULTIMATE SCANNER** 🚨\n"
    header += f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
    header += "🏆 **BẢNG XẾP HẠNG SIÊU CỔ PHIẾU:**\n"
    for i, item in enumerate(top_5, 1):
        header += f"{i}. **{item['ticker']}** | Điểm: `{item['score']}/10` | RS: `{item['rs']}`\n"
    send_telegram(header)

    # 2. CHI TIẾT KÈO (Score >= 7)
    for f in final_list:
        if f['score'] >= 7:
            msg = f"💎 **{f['ticker']}** - {f['name']}\n"
            msg += f"∟ Vốn hóa: {f['cap']} Tỷ | CP: {f['shares']} Tr\n"
            msg += f"∟ Giá: **{f['price']}** ({f['change']}%)\n\n"
            
            msg += f"📊 **PHÂN TÍCH ĐỊNH LƯỢNG (QUANT)**\n"
            msg += f"∟ Cá mập (MCDX): `{f['mcdx_r']}%` {'🔴' * int(f['mcdx_r']//20)}\n"
            msg += f"∟ Sức mạnh RS: **{f['rs']}** so với VN-Index\n"
            msg += f"∟ Siết nền VCP: {'✅ Đạt' if f['tight'] else '❌ Chưa chặt'}\n"
            
            msg += f"📈 **TÍN HIỆU CHIẾN THUẬT:**\n"
            for v in f['vsa']: msg += f"∟ {v}\n"
            
            msg += f"\n🎯 **MỤC TIÊU & CẮT LỖ (PIVOT)**\n"
            msg += f"∟ Mục tiêu 1 (R1): **{f['r1']}**\n"
            msg += f"∟ Mục tiêu 2 (R2): **{f['r2']}**\n"
            msg += f"∟ Mục tiêu 3 (R3): **{f['r3']}**\n"
            msg += f"∟ Cắt lỗ cứng (S1): **{f['s1']}**\n"
            msg += f"—————————————\n"
            msg += "⚡️ *Phát hiện sớm - Vào nhanh - Ra gọn!*"
            send_telegram(msg)

if __name__ == "__main__":
    main()
              
