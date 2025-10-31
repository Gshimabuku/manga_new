import streamlit as st
import requests
import pandas as pd
import time

# --- 楽天 Books API 設定 ---
API_ENDPOINT = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"

# APIキー設定
def get_api_keys():
    import os
    api_key = None
    affiliate_id = None
    
    # Streamlit secrets から取得
    try:
        api_key = st.secrets["rakuten"]["applicationId"]
        affiliate_id = st.secrets["rakuten"]["affiliateId"]
        st.success("✅ Streamlit secretsから設定を読み込みました")
        return api_key, affiliate_id
    except KeyError:
        st.warning("⚠️ Streamlit secretsで楽天設定が見つかりません")
    except Exception as e:
        st.warning(f"⚠️ Streamlit secrets読み込みエラー: {e}")
    
    return api_key, affiliate_id

# 設定取得
try:
    API_KEY, AFFILIATE_ID = get_api_keys()
except Exception as e:
    st.error(f"設定エラー: {e}")
    st.stop()

def title_matches(book_title, search_title):
    """
    タイトルが検索条件にマッチするかを判定する関数
    スペース区切りの単語がすべて含まれているかチェック
    """
    # 大文字小文字を統一して比較
    book_title_lower = book_title.lower()
    search_title_lower = search_title.lower()
    
    # 検索タイトルをスペースで分割
    search_words = search_title_lower.split()
    
    # すべての単語が本のタイトルに含まれているかチェック
    for word in search_words:
        if word not in book_title_lower:
            return False
    
    return True

def search_books_with_volume(title, volume_number, retries=3, max_pages=5):
    """
    タイトルで検索し、指定した巻数が含まれる書籍を抽出する
    最大5ページまで検索結果を取得
    """
    all_results = []
    
    # APIのタイトルパラメータ用（スペースをプラスに変換）
    api_title = title.replace(' ', '+')
    
    # 各ページを順次取得
    for page in range(1, max_pages + 1):
        params = {
            'applicationId': API_KEY,
            'affiliateId': AFFILIATE_ID,
            'title': api_title,
            'sort': '-releaseDate',
            'hits': 30,
            'page': page
        }
        
        page_results = []
        
        for attempt in range(retries):
            try:
                response = requests.get(API_ENDPOINT, params=params, timeout=10)
                if response.status_code == 200:
                    break
                else:
                    st.error(f"ページ{page} エラー: {response.status_code} (試行 {attempt+1}/{retries})")
            except requests.exceptions.RequestException as e:
                st.error(f"ページ{page} 通信エラー: {e} (試行 {attempt+1}/{retries})")
            
            # エラー時は少し待って再試行
            if attempt < retries - 1:
                time.sleep(1)
        else:
            st.warning(f"ページ{page}のAPIが応答しませんでした。")
            continue

        try:
            data = response.json()
            books = data.get("Items", [])
            
            # このページに結果がない場合は終了
            if not books:
                st.info(f"ページ{page}で検索結果が終了しました。")
                break
            
            # タイトルマッチングとフィルタリング
            for book_item in books:
                book = book_item["Item"]
                book_title = book["title"]
                
                # まず、タイトルでフィルタリング
                if not title_matches(book_title, title):
                    continue
                
                # 巻数でフィルタリング
                if volume_number and volume_number not in book_title:
                    continue
                
                # 条件を満たす書籍を結果に追加
                book_data = {
                    "タイトル": book_title,
                    "ISBN": book["isbn"],
                    "出版日": book["salesDate"],
                    "価格": f"{book.get('itemPrice', '不明')}円",
                    "出版社": book.get("publisherName", "不明")
                }
                
                # 重複チェック（ISBNで判定）
                if not any(result["ISBN"] == book_data["ISBN"] for result in all_results):
                    page_results.append(book_data)
            
            all_results.extend(page_results)
            
            # このページで取得した件数を表示
            if page_results:
                st.info(f"ページ{page}: {len(page_results)}件の書籍を取得")
            
            # API制限を考慮して少し待機
            if page < max_pages:
                time.sleep(0.5)
                
        except Exception as e:
            st.error(f"ページ{page} データ処理エラー: {e}")
            continue
    
    if not all_results:
        st.warning("該当する本が見つかりませんでした。")
    
    return all_results

def main():
    st.title("📚 新規書籍検索")
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
        with st.spinner("検索中... (最大5ページまで検索します)"):
            results = search_books_with_volume(title.strip(), volume_number.strip())
        
        # 結果表示
        st.subheader("📊 検索結果")
        
        if results:
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True)
            st.success(f"✅ {len(results)}件の書籍が見つかりました！")
            
            # 検索結果の要約
            if volume_number.strip():
                st.info(f"「{title}」の{volume_number}巻に関連する書籍を表示しています（最大5ページまで検索）")
            else:
                st.info(f"「{title}」に関連する全ての書籍を表示しています（最大5ページまで検索）")
        else:
            st.warning("⚠️ 検索条件に一致する書籍は見つかりませんでした")
            
            # 検索のヒント
            st.markdown("""
            **検索のコツ:**
            - タイトルは部分一致で検索され、スペース区切りの単語すべてが含まれる書籍を抽出します
            - 巻数は「108」のように数字のみ入力してください
            - 巻数を指定しない場合、そのタイトルの全ての書籍が表示されます
            - 例：「ONE PIECE」と入力すると、「ONE」と「PIECE」両方を含む書籍のみが表示されます
            """)

    # デバッグ情報
    with st.expander("🔧 デバッグ情報"):
        st.write("**API設定状況:**")
        st.write(f"- 楽天API Key: {'✅ 設定済み' if API_KEY else '❌ 未設定'}")
        st.write(f"- 楽天Affiliate ID: {'✅ 設定済み' if AFFILIATE_ID else '❌ 未設定'}")
        st.write(f"- API Endpoint: {API_ENDPOINT}")

if __name__ == "__main__":
    main()
