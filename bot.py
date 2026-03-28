import os
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta
from vnstock import stock_historical_data, financial_flow, listing_companies

# ==========================================
# 1. CẤU HÌNH & CHỈ SỐ KEY TỪ ẢNH
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Ngưỡng logic MCDX được suy luận từ ảnh (MCDX Ca Map/Dau Co)
MCDX_CAP_MAP_THRESHOLD = 3.0   # Điểm số Dòng tiền Cá mập (đỏ) cần đạt
MCDX_DAU_CO_THRESHOLD = 15.0  # Điểm số Dòng tiền Đầu cơ (vàng) cần đạt
SOS_VOL_AVG_MULT = 1.6        # Tín hiệu SOS: Volume > 1.6 lần trung bình 20 phiên
PRICE_SOS_PCT = 3.2           # Tín hiệu SOS: Giá tăng > 3.2%

# ==========================================
# 2. HÀM GỬI TELEGRAM NÂNG CAO
# ==========================================
def send_telegram_super_report(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

# ==========================================
# 3. THUẬT TOÁN PHÂN TÍCH DÒNG TIỀN MCDX MÔ PHỎNG
# ==========================================
def calculate_mcdx_logic(df):
    """
    Mô phỏng logic MCDX (Dòng tiền Cá mập vs Đầu cơ) dựa trên ADX và Price/Vol action.
    Amibroker thường dùng công thức tùy chỉnh; Python cần proxy chính xác.
    """
    # Tính ADX(14) - Chỉ số sức mạnh xu hướng
    df.ta.adx(length=14, append=True)
    df.rename(columns={'ADX_14': 'ADX', 'DMP_14': 'DI_plus', 'DMN_14': 'DI_minus'}, inplace=True)
    
    # Tính Volume trung bình 20 phiên
    df['vol_avg20'] = df['volume'].rolling(window=20).mean()

    # Tính toán "Điểm số Cá mập" (MCDX Red Bar)
    # Tích hợp: ADX cao, DI+ > DI-, Giá tăng, Volume cao
    df['score_cap_map'] = (
        (df['ADX'] / 20).clip(upper=1.0) * 0.4 + # Trọng số ADX
        (df['volume'] / df['vol_avg20']).clip(upper=3.0) * 0.3 + # Trọng số Volume
        ((df['close'] - df['close'].shift(1)) / df['close'].shift(1)).clip(lower=0, upper=0.05) * 60 + # Trọng số Price tăng
        (df['DI_plus'] > df['DI_minus']).astype(int) * 0.2
    ).rolling(window=5).mean().fillna(0) # Làm mượt 5 phiên

    # Tính toán "Điểm số Đầu cơ" (MCDX Yellow Bar)
    # Tích hợp: ADX trung bình, Volume trung bình, Giá biến động
    df['score_dau_co'] = (
        (35 / df['ADX']).clip(upper=1.0) * 0.3 + # Thích ADX trung bình/yếu
        (df['vol_avg20'] / df['volume']).clip(upper=1.0) * 0.3 + # Thích Volume trung bình
        ((df['close'] - df['low']) / (df['high'] - df['low'])).fillna(0) * 0.4
    ).rolling(window=5).mean().fillna(0) # Làm mượt 5 phiên

    return df

# ==========================================
# 4. HÀM PHÂN TÍCH SIÊU CẤP CHO MỘT MÃ CỔ PHIẾU
# ==========================================
def analyze_stock_super_mode(ticker):
    try:
        # 1. Lấy dữ liệu cơ bản (như trong ảnh)
        # Lấy tên công ty
        listing_df = listing_companies()
        company_name = listing_df[listing_df['ticker'] == ticker]['organ_name'].values[0]

        # Lấy thông tin tài chính cơ bản
        financial_df = financial_flow(symbol=ticker, report_type='quarter', report_range='near_4_quarters')
        latest_financial = financial_df.iloc[-1]
        
        # Suy luận: Amibroker trong ảnh lấy Vốn hóa/Vốn điều lệ, Python cần tính
        market_cap_ty = round(latest_financial.get('market_cap', 0) / 1e12, 1)
        shares_outstanding_triu = round(latest_financial.get('equity', 0) / 1e12 * 10, 0) # Suy luận số CP

        # 2. Lấy dữ liệu lịch sử (180 phiên)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=270)
        df = stock_historical_data(symbol=ticker, start_date=start_date.strftime('%Y-%m-%d'), end_date=end_date.strftime('%Y-%m-%d'), resolution="1D", type="stock")
        if df is None or len(df) < 50: return None

        # 3. Tính toán các chỉ báo kỹ thuật
        df.ta.ema(length=20, append=True) # Xu hướng ngắn hạn (Tốc độ)
        df.ta.ema(length=50, append=True) # Xu hướng trung hạn (Căn bản)
        df.ta.rsi(length=14, append=True) # Động lượng

        # 4. Tính toán Pivot Point để dự báo Target/Stop Loss
        pp_length = 20 # Dùng 20 phiên làm nền
        df['P'] = (df['high'].rolling(pp_length).mean() + df['low'].rolling(pp_length).mean() + df['close'].rolling(pp_length).mean()) / 3
        df['S1'] = (2 * df['P']) - df['high'].rolling(pp_length).max()
        df['R1'] = (2 * df['P']) - df['low'].rolling(pp_length).min()
        df['R2'] = df['P'] + (df['high'].rolling(pp_length).max() - df['low'].rolling(pp_length).min())
        df['R3'] = df['high'].rolling(pp_length).max() + 2 * (df['P'] - df['low'].rolling(pp_length).min())

        # 5. Phân tích MCDX
        df = calculate_mcdx_logic(df)

        # Lấy dữ liệu phiên gần nhất
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # 6. Logic Tín hiệu Mua/Bán/Nắm giữ (Mô phỏng nến màu trong ảnh)
        # Nến xanh = EMA20 > EMA50; Nến đỏ = EMA20 <= EMA50
        status_candle = "✅ Nến xanh (Tăng)" if curr['EMA_20'] > curr['EMA_50'] else "❌ Nến đỏ (Giảm)"
        
        # Tín hiệu Mua/Bán/Golden Cross/Dead Cross
        action_signal = ""
        if curr['EMA_20'] > curr['EMA_50'] and prev['EMA_20'] <= prev['EMA_50']:
            action_signal = "🎯 MUA - MỞ VỊ THẾ"
        elif curr['EMA_20'] < curr['EMA_50'] and prev['EMA_20'] >= prev['EMA_50']:
            action_signal = "⚠️ BÁN - ĐỨNG NGOÀI"
        elif curr['EMA_20'] > curr['EMA_50']:
            action_signal = "🛡️ TIẾP TỤC NẮM GIỮ"
        else:
            action_signal = "🚫 ĐỨNG NGOÀI QUAN SÁT"

        # Xu hướng tổng thể (Như trong ảnh)
        trend_status = "Uptrend" if curr['EMA_20'] > curr['EMA_50'] and curr['close'] > curr['EMA_50'] else "Downtrend"

        # 7. Tính SOS và Spring nâng cao
        price_change_pct = round(((curr['close'] - prev['close']) / prev['close']) * 100, 2)
        sos_vol_ratio = round(curr['volume'] / curr['vol_avg20'], 2)
        
        signals_advanced = []
        if price_change_pct > PRICE_SOS_PCT and sos_vol_ratio > SOS_VOL_AVG_MULT:
            signals_advanced.append("🚀 SOS: Giá tăng mạnh + Vol đột biến (Dòng tiền Big Boy)")
        if prev['close'] < curr['EMA_50'] and curr['close'] > curr['EMA_50'] and curr['volume'] < curr['vol_avg20']:
            signals_advanced.append("🛡️ SPRING: Rút chân trên nền EMA50 (Cú rũ bỏ)")

        # 8. Phân tích Dòng tiền MCDX nâng cao
        mcdx_status = ""
        mcdx_color = ""
        cap_map_score = round(curr['score_cap_map'], 1)
        dau_co_score = round(curr['score_dau_co'], 1)

        if cap_map_score > MCDX_CAP_MAP_THRESHOLD and dau_co_score > MCDX_DAU_CO_THRESHOLD:
            mcdx_status = "🔥 Dòng tiền Lớn nhập cuộc cùng Dầu cơ mạnh"
            mcdx_color = "🔴🟡" # Mô phỏng màu đỏ và vàng
        elif cap_map_score > MCDX_CAP_MAP_THRESHOLD:
            mcdx_status = "🔴 Dòng tiền Lớn chiếm ưu thế"
            mcdx_color = "🔴"
        elif dau_co_score > MCDX_DAU_CO_THRESHOLD:
            mcdx_status = "🟡 Dòng tiền Đầu cơ chiếm ưu thế"
            mcdx_color = "🟡"
        else:
            mcdx_status = "🟢 Dòng tiền Cá con/Yếu"
            mcdx_color = "🟢"

        # 9. Target & Stop Loss Dự báo
        target_1 = round(curr['R1'], 1)
        target_2 = round(curr['R2'], 1)
        target_3 = round(curr['R3'], 1)
        cut_loss = round(curr['S1'], 1)

        # Trả về kết quả tổng hợp
        return {
            "ticker": ticker,
            "company_name": company_name,
            "market_cap_ty": market_cap_ty,
            "shares_outstanding_triu": shares_outstanding_triu,
            "price": curr['close'],
            "change_pct": price_change_pct,
            "volume": curr['volume'],
            "rsi": round(curr['RSI_14'], 1),
            "status_candle": status_candle,
            "trend_status": trend_status,
            "action_signal": action_signal,
            "signals_advanced": signals_advanced,
            "mcdx_status": mcdx_status,
            "mcdx_color": mcdx_color,
            "target_1": target_1,
            "target_2": target_2,
            "target_3": target_3,
            "cut_loss": cut_loss,
            "is_buying_signal": action_signal == "🎯 MUA - MỞ VỊ THẾ"
        }
    except Exception as e:
        print(f"Lỗi khi phân tích {ticker}: {e}")
        return None

# ==========================================
# 5. HÀM CHÍNH (MAIN FUNCTION)
# ==========================================
def main():
    # Danh sách quét mở rộng (Ví dụ: VN30 + các mã cơ bản)
    watch_list = ['MSN', 'VHM', 'MVN', 'SGP', 'ACV', 'SSI', 'VCI', 'HCM', 'HPG', 'GEX', 'DXG', 'DIG', 'PVD', 'PVC']
    findings = []

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Đang quét siêu cấp {len(watch_list)} mã cổ phiếu...")
    
    for ticker in watch_list:
        res = analyze_stock_super_mode(ticker)
        if res: findings.append(res)

    if findings:
        for f in findings:
            # Chỉ gửi tin nhắn nếu có tín hiệu Mua hoặc tín hiệu Nâng cao đặc biệt
            if not (f['is_buying_signal'] or f['signals_advanced']):
                continue

            msg = f"🔥 **BÁO CÁO TÍN HIỆU SIÊU CẤP** 🔥\n\n"
            
            # Phần 1: Thông tin cơ bản (Giống ảnh)
            msg += f"💎 **{f['ticker']}** \- {f['company_name']}\n"
            msg += f"∟ Giá: {f['price']} \({f['change_pct']}% / {f['volume']}\)\n"
            msg += f"∟ Vốn hóa: {f['market_cap_ty']} Tỷ\n"
            msg += f"∟ Số lượng CP: {f['shares_outstanding_triu']} Triệu\n\n"
            
            # Phần 2: Thống kê Robot (Giống ảnh)
            msg += f"📊 **Thống kê Robot SUPER\_BOT v1\.0** \n"
            msg += f"∟ RSI: {f['rsi']}\n"
            msg += f"∟ Xu hướng: {f['trend_status']} \- {f['status_candle']}\n"
            msg += f"∟ Hành động: **{f['action_signal']}**\n\n"
            
            # Phần 3: Phân tích Nâng cao (Vượt trội)
            msg += f"📈 **Phân tích Dòng tiền DÒNG TIỀN NÂNG CAO** \n"
            msg += f"∟ Dòng tiền MCDX: {f['mcdx_color']} {f['mcdx_status']}\n"
            for sig in f['signals_advanced']:
                msg += f"∟ **{sig}**\n"
            if not f['signals_advanced']: msg += f"∟ Không có tín hiệu SOS/Spring đặc biệt\.\n"
            msg += "\n"

            # Phần 4: Target & Stop Loss (Giống ảnh)
            msg += f"🎯 **Dự báo Mục tiêu & Cắt lỗ** \n"
            msg += f"∟ VÙNG MUA GỢI Ý: {f['price']} \- {round(f['price'] * 1.01, 1)}\n"
            msg += f"∟ **Mục tiêu dự kiến:** {f['target_1']} \-\-\> {f['target_2']} \-\-\> {f['target_3']}\n"
            msg += f"∟ **Bán cutloss khi giá thủng:** **{f['cut_loss']}**\n\n"

            # Phần 5: Footer & Link (Giống ảnh)
            msg += f"—————————————\n"
            msg += f"Website: SuperBot\.vn \| Zalo: 0123456789"
            
            # Gửi tin nhắn về Telegram
            send_telegram_super_report(msg)
            print(f"Đã gửi cảnh báo siêu cấp cho {f['ticker']}.")

    else:
        print("Không có tín hiệu đặc biệt nào đạt tiêu chí.")

if __name__ == "__main__":
    main()
       
                                
