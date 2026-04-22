# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 環境規則
- 所有 `pip install`、`python`、`uvicorn` 指令都必須加 `conda run -n badminton` 前綴
- 例如：`conda run -n badminton pip install fastapi`
- 不可以直接執行 `pip install` 或 `python`

## 啟動伺服器

```bash
conda run -n badminton uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

## 專案說明

區域網路（LAN）羽球團體賽即時計分系統。紅隊 vs 白隊，4 個場地同時進行，各場地分數累積為兩隊總分。所有狀態存在記憶體，無資料庫。

## 架構

**後端**：`server.py` — FastAPI + WebSocket，單一全域 `state` dict，每次狀態變更透過 `broadcast()` 推送給所有 WebSocket clients。

**前端**：純 HTML + Vanilla JS，由 FastAPI `StaticFiles` serve，無前端框架。四個頁面：

| URL | 檔案 | 用途 |
|-----|------|------|
| `/` | `display.html` | 主桌大螢幕，顯示累積總分與各場明細 |
| `/court?id=N` | `court.html` | 手機計分頁，每個場地一支手機 |
| `/admin` | `admin.html` | 管理頁，上傳賽程、查看場地狀態、歷史紀錄 |
| `/schedule` | `schedule.html` | 公開賽程表，選手查閱對戰組合與即時比分 |

## 全域狀態結構

```python
state = {
    "cumulative": {"red": 0, "white": 0},   # 已完賽局的累積總分
    "courts": {
        1: {
            "red": 0, "white": 0,            # 本場目前比分
            "red_player": "", "white_player": "",  # 本場選手
            "match_active": False,            # True = 比賽進行中
            "match_index": 0,                 # 已完成幾場（指向 queue 的下一場）
        }
    },
    "schedule": [                             # 從 CSV 匯入的賽程
        {
            "round": 1,
            "time": "14:30 - 14:45",
            "courts": {
                "1": {"red_player": "W1", "white_player": "B1"}
            }
        }
    ],
    "history": [                              # 每場比賽結束後存入
        {
            "court": 1, "round": 1, "time": "...",
            "red_player": "W1", "white_player": "B1",
            "red": 5, "white": 3
        }
    ]
}
```

## 比賽流程

每個場地獨立運作，不需要全局同步：

1. 管理員在 `/admin` 上傳賽程 CSV → 系統自動預載各場地第一場選手
2. 場地操作員在 `court.html` 確認選手名稱（可手動修改）→ 按「開始比賽」
3. 計分：點擊整個隊伍區域 = +1；-1 按鈕扣分；分數最低為 0
4. 按「結束本場」→ 分數存入 `history`，累積至 `cumulative`，自動帶入下一場選手
5. 若賽程已結束仍可手動輸入選手繼續加賽

**計分保護**：WebSocket 計分訊息只在 `match_active = True` 時生效。

## 關鍵 API

| 方法 | 路徑 | 說明 |
|------|------|------|
| `WebSocket` | `/ws` | 計分事件（`{court, team, delta}`），廣播完整狀態給所有 clients |
| `POST` | `/api/schedule` | 上傳賽程（**同時重置歷史與累積分**） |
| `POST` | `/court/{id}/start` | 開始比賽，body: `{red_player, white_player}` |
| `POST` | `/court/{id}/end` | 結束比賽，存歷史，載入下一場 |
| `POST` | `/court/add` | 新增場地（自動重新編號） |
| `POST` | `/court/remove/{id}` | 移除場地（自動重新編號） |
| `POST` | `/reset/{court_id}` | 重置單一場地分數 |
| `GET` | `/state` | 回傳完整廣播狀態（除錯用） |

## Broadcast 格式

每次狀態變更都廣播此結構給所有 WebSocket clients：

```json
{
  "type": "update",
  "cumulative": {"red": 10, "white": 8},
  "totals": {"red": 2, "white": 1},
  "courts": {
    "1": {
      "red": 2, "white": 1,
      "red_player": "W1", "white_player": "B1",
      "match_active": true,
      "match_index": 1,
      "matches_total": 8,
      "queue": [{"round": 1, "time": "...", "red_player": "W1", "white_player": "B1"}, ...]
    }
  },
  "schedule": [...],
  "history": [...]
}
```

`totals` 是當前各場地比分加總（不含已結束局）；顯示頁面以 `cumulative + totals` 作為即時總分。

## CSV 賽程格式

```
局數,時間,場地1紅,場地1白,場地2紅,場地2白,場地3紅,場地3白,場地4紅,場地4白
1,14:30 - 14:45,W1,B1,W8,B5,W3,B3,W4,B4
```

範本位於 `static/template.csv`，可從 `/admin` 下載。欄位數決定場地數（`(columns - 2) / 2`）。
