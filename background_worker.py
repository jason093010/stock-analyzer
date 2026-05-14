# background_worker.py
import json
import time
from datetime import datetime, timezone, timedelta
from app import fetch_data, calc_indicators, calc_score

TW_TZ = timezone(timedelta(hours=8))

# 您監控的排行榜清單
TRACK_LIST = [
    "2330.TW", "2454.TW", "2317.TW", "2382.TW", "2308.TW", 
    "2881.TW", "2603.TW", "NVDA", "AAPL", "MSFT", "TSLA"
]

def generate_leaderboard():
    print(f"[{datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')}] 啟動 AI 權重計算...")
    results = []
    for sym in TRACK_LIST:
        try:
            h, info, err = fetch_data(sym, "3mo") 
            if h is not None and not h.empty:
                ind = calc_indicators(h)
                score = calc_score(ind, info)
                results.append({
                    "sym": sym.replace(".TW", ""),
                    "name": info.get("longName", sym),
                    "score": score["total"],
                    "status": ind["status"],
                    "dims": {"技術": score["trend"], "動能": score["mom"], "量能": score["vol"], "位階": score["pos"], "布林": score["bb"]},
                    "update_time": datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
                })
        except Exception as e:
            print(f"分析 {sym} 出錯: {e}")
        time.sleep(2) 
    
    results = sorted(results, key=lambda x: x["score"], reverse=True)[:10]
    with open("leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    print("✅ 排行榜已更新至 leaderboard.json")

if __name__ == "__main__":
    while True:
        generate_leaderboard()
        print("💤 進入休眠，3 小時後進行下次自動更新...")
        time.sleep(10800) # 3 小時更新一次