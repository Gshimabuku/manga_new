import streamlit as st
import requests
import pandas as pd
import time

# --- 楽天 Books API 設定 ---
API_ENDPOINT = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"

# APIキー設定（app.pyと同じ方法）
def get_api_keys():
    """APIキーを複数の方法で取得を試みる"""
    import os
    api_key = None
    affiliate_id = None
    
    # 方法1: Streamlit secrets
    try:
        api_key = st.secrets["rakuten"]["applicationId"]
        affiliate_id = st.secrets["rakuten"]["affiliateId"]
        st.success("✅ Streamlit secretsから設定を読み込みました")
        return api_key, affiliate_id
    except KeyError:
        st.warning("⚠️ Streamlit secretsで楽天設定が見つかりません")
    except Exception as e:
        st.warning(f"⚠️ Streamlit secrets読み込みエラー: {e}")
    
    # 方法2: 環境変数
    try:
        api_key = os.getenv("RAKUTEN_APPLICATION_ID")
        affiliate_id = os.getenv("RAKUTEN_AFFILIATE_ID")
        if api_key and affiliate_id:
            st.success("✅ 環境変数から設定を読み込みました")
            return api_key, affiliate_id
        else:
            st.warning("⚠️ 環境変数に楽天設定が見つかりません")
    except Exception as e:
        st.warning(f"⚠️ 環境変数読み込みエラー: {e}")
    
    # 方法3: デフォルト値（開発用）
    if not api_key or not affiliate_id:
        st.error("❌ 楽天APIキーが見つかりません。以下のいずれかの方法で設定してください：")
        st.markdown("""
        **設定方法:**
        1. `.streamlit/secrets.toml` に設定を追加
        2. 環境変数 `RAKUTEN_APPLICATION_ID` と `RAKUTEN_AFFILIATE_ID` を設定
        3. Streamlit Cloud の場合、アプリ設定でSecretsを追加
        """)
        st.stop()
    
    return api_key, affiliate_id

# 設定取得
try:
    API_KEY, AFFILIATE_ID = get_api_keys()
except Exception as e:
    st.error(f"設定エラー: {e}")
    st.stop()

def search_books_with_volume(title, volume_number, retries=3):
    """
    タイトルで検索し、指定した巻数が含まれる書籍を抽出する
    """
    results = []
    params = {
        'applicationId': API_KEY,
        'affiliateId': AFFILIATE_ID,
        'title': title,
        'sort': '-releaseDate',
        'hits': 30
    }
    
    for attempt in range(retries):
        try:
            response = requests.get(API_ENDPOINT, params=params, timeout=10)
            if response.status_code == 200:
                break
            else:
                st.error(f"エラー: {response.status_code} (試行 {attempt+1}/{retries})")
        except requests.exceptions.RequestException as e:
            st.error(f"通信エラー: {e} (試行 {attempt+1}/{retries})")
        
        # エラー時は少し待って再試行
        if attempt < retries - 1:
            time.sleep(1)
    else:
        st.error("APIが応答しませんでした。後でもう一度お試しください。")
        return results

    try:
        data = response.json()
        books = data.get("Items", [])
        
        if not books:
            st.warning("該当する本が見つかりませんでした。")
            return results

        # 巻数でフィルタリング
        if volume_number:
            # 複数の巻数表現に対応
            volume_patterns = [
                volume_number + "巻",
                volume_number + "話",
                f"第{volume_number}巻",
                f"({volume_number})",
                f" {volume_number} ",
                f"vol.{volume_number}",
                f"Vol.{volume_number}",
                f"VOL.{volume_number}"
            ]
            
            for book_item in books:
                book = book_item["Item"]
                book_title = book["title"]
                
                # いずれかのパターンにマッチする場合に結果に追加
                for pattern in volume_patterns:
                    if pattern in book_title:
                        results.append({
                            "タイトル": book_title,
                            "ISBN": book["isbn"],
                            "出版日": book["salesDate"],
                            "価格": f"{book.get('itemPrice', '不明')}円",
                            "出版社": book.get("publisherName", "不明")
                        })
                        break  # 一つでもマッチしたら次の本へ
        else:
            # 巻数指定なしの場合は全件表示
            for book_item in books:
                book = book_item["Item"]
                results.append({
                    "タイトル": book["title"],
                    "ISBN": book["isbn"],
                    "出版日": book["salesDate"],
                    "価格": f"{book.get('itemPrice', '不明')}円",
                    "出版社": book.get("publisherName", "不明")
                })
        
        return results
        
    except Exception as e:
        st.error(f"データ処理エラー: {e}")
        return results

def main():
    st.title("📚 楽天Books 書籍検索")
    st.markdown("タイトルと巻数を指定して楽天Booksから書籍を検索します")

    # 入力フォーム
    with st.form("search_form"):
        st.subheader("📝 検索条件")
        
        title = st.text_input(
            "作品タイトル *（必須）",
            placeholder="例: ワンピース",
            help="検索したい作品のタイトルを入力してください"
        )
        
        volume_number = st.text_input(
            "巻数（任意）",
            placeholder="例: 108",
            help="特定の巻数を検索したい場合に入力してください。空白の場合は全ての巻を表示します。"
        )
        
        submitted = st.form_submit_button("🔍 検索開始")
    
    # 検索実行
    if submitted:
        if not title.strip():
            st.error("❌ タイトルを入力してください")
            return
        
        # 検索条件の表示
        st.subheader("🔎 検索条件")
        st.write(f"**タイトル:** {title}")
        if volume_number.strip():
            st.write(f"**巻数:** {volume_number}")
        else:
            st.write("**巻数:** 指定なし（全巻表示）")
        
        # 検索実行
        with st.spinner("検索中..."):
            results = search_books_with_volume(title.strip(), volume_number.strip())
        
        # 結果表示
        st.subheader("📊 検索結果")
        
        if results:
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True)
            st.success(f"✅ {len(results)}件の書籍が見つかりました！")
            
            # 検索結果の要約
            if volume_number.strip():
                st.info(f"「{title}」の{volume_number}巻に関連する書籍を表示しています")
            else:
                st.info(f"「{title}」に関連する全ての書籍を表示しています")
        else:
            st.warning("⚠️ 検索条件に一致する書籍は見つかりませんでした")
            
            # 検索のヒント
            st.markdown("""
            **検索のコツ:**
            - タイトルは完全一致でなくても部分一致で検索されます
            - 巻数は「108」のように数字のみ入力してください
            - 巻数を指定しない場合、そのタイトルの全ての書籍が表示されます
            """)

    # デバッグ情報
    with st.expander("🔧 デバッグ情報"):
        st.write("**API設定状況:**")
        st.write(f"- 楽天API Key: {'✅ 設定済み' if API_KEY else '❌ 未設定'}")
        st.write(f"- 楽天Affiliate ID: {'✅ 設定済み' if AFFILIATE_ID else '❌ 未設定'}")
        st.write(f"- API Endpoint: {API_ENDPOINT}")

if __name__ == "__main__":
    main()
