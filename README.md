# RMP Mobile - Cloud Edition

YouTube Music Player for Smartphones (完全クラウド版)

## 特徴

- 🌐 **PC不要** - スマホだけで完結
- 📱 **IndexedDB対応** - スマホのローカルストレージに曲を保存
- 🎵 **YouTube対応** - 曲名またはURLで検索・ダウンロード
- 📂 **プレイリスト管理** - カテゴリー分けして管理
- ⭐ **お気に入り** - よく聴く曲をマーク
- 🚀 **無料クラウド** - Render + Netlify で完全無料

## アーキテクチャ

```
┌─────────────────────┐
│   Smartphone        │
│  (IndexedDB)        │  ← 音源ファイル保存
│  (Vue.js UI)        │
└──────────┬──────────┘
           │
    ┌──────▼───────┐
    │  Netlify     │  ← フロントエンド (index.html)
    │ (静的ホスト)  │
    └──────┬────────┘
           │
    ┌──────▼──────────┐
    │  Render        │  ← バックエンド (Flask)
    │  (Flask API)   │     - YouTube DL
    │  (SQLite)      │     - ffmpeg エンコード
    │  (メタデータDB) │     - API提供
    └────────────────┘
```

## デプロイ手順

### 1. GitHub にリポジトリを作成

```bash
cd RMP-deploy
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/rmp-mobile.git
git push -u origin main
```

### 2. Render でバックエンドをデプロイ

1. [Render.com](https://render.com) にアクセス
2. 「New」→「Web Service」
3. GitHub リポジトリを接続
4. 以下を設定：
   - **Name**: `rmp-mobile`
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
5. 「Create Web Service」でデプロイ開始
6. デプロイ完了後、URL をメモ（例：`https://rmp-mobile.onrender.com`）

### 3. Netlify でフロントエンドをデプロイ

#### オプション A: index.html をそのままホスト

1. [Netlify](https://app.netlify.com) にアクセス
2. 「Add new site」→「Upload an existing project」
3. `index.html` をアップロード
4. サイトデプロイ完了

#### オプション B: GitHub 連携

1. Netlify にサインイン
2. 「New site from Git」
3. GitHub リポジトリ接続
4. Build settings:
   - Build command: (なし)
   - Publish directory: `.`

### 4. API URL をフロントエンドに設定

`index.html` の先頭で API URL を設定：

```javascript
const API_URL = 'https://rmp-mobile.onrender.com';
```

または、環境変数で制御：

```html
<script>
    const API_URL = import.meta.env.VITE_API_URL || 'https://rmp-mobile.onrender.com';
</script>
```

## ローカルテスト

```bash
# バックエンド
pip install -r requirements.txt
python server.py
# http://localhost:5000 でアクセス

# フロントエンド
# ブラウザで index.html を開く
```

## API エンドポイント

### インポート
- **POST** `/api/import`
  - Body: `{"url": "YouTube URL or search query"}`
  - Response: `{"songs": [...]}`

### 曲管理
- **GET** `/api/songs` - すべての曲を取得
- **DELETE** `/api/songs/<id>` - 曲を削除
- **POST** `/api/songs/<id>/favorite` - お気に入り設定
- **PUT** `/api/songs/<id>/meta` - タイトル・アーティスト編集

### プレイリスト
- **GET** `/api/playlists` - プレイリスト一覧
- **POST** `/api/playlists` - 新規作成
- **PUT** `/api/playlists/<id>` - 名前変更
- **DELETE** `/api/playlists/<id>` - 削除
- **GET** `/api/playlists/<id>` - 詳細
- **POST** `/api/playlists/<id>/songs` - 曲を追加
- **DELETE** `/api/playlists/<id>/songs/<song_id>` - 曲を削除

## トラブルシューティング

### ダウンロードが遅い / タイムアウト

Render 無料プランはスリープ機能があります：
- 15分アクセスなしで自動スリープ
- 次のアクセス時に起動（5～10秒遅延）

### 音声ファイルが保存されない

IndexedDB がブロックされていないか確認：
- ブラウザの設定を確認
- プライベート/シークレットモードでテスト

### CORS エラーが出る

バックエンド (`server.py`) に CORS 設定済みです。確認：
```python
from flask_cors import CORS
CORS(app)
```

## 無料プランの制限

| サービス | 制限 |
|--------|-----|
| **Render** | 750時間/月無料、スリープあり |
| **Netlify** | 無制限トラフィック |
| **IndexedDB** | ブラウザ依存（通常50MB～） |
| **ffmpeg** | 実行可能 |

## 今後の拡張

- [ ] クラウドストレージ連携（Google Drive等）
- [ ] ユーザー認証・同期
- [ ] 歌詞表示
- [ ] キー変更機能
- [ ] モバイルアプリ化

## ライセンス

個人使用のみ

## サポート

問題が発生した場合、ブラウザコンソール (F12) でエラーメッセージを確認してください。

---

**2026.06.29 版**
