import streamlit as st
import requests
import pandas as pd
import time
import gspread
from google.oauth2.service_account import Credentials
try:
    from gspread.exceptions import SpreadsheetNotFound, APIError
except Exception:
    from gspread import SpreadsheetNotFound, APIError

# --- 楽天 Books API 設定 ---
API_ENDPOINT = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"

# Google Sheets認証
def get_gspread_client():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly"
            ]
        )
        return gspread.authorize(creds)
    except KeyError as e:
        st.error(f"設定エラー: Google Cloud認証情報が見つかりません。\nエラー詳細: {e}")
        return None
    except Exception as e:
        st.error(f"Google Sheets認証でエラーが発生しました: {e}")
        return None

# スプレッドシートへの書き込み機能
def add_to_spreadsheet(title, search_title, volume):
    try:
        gc = get_gspread_client()
        if gc is None:
            return False
            
        # スプレッドシート名をsecretsから取得
        spreadsheet_name = st.secrets["env"]["sheet_name"]
        spreadsheet = gc.open(spreadsheet_name)
        worksheet = spreadsheet.sheet1  # 最初のシートを使用
        
        # 新しい行を追加
        new_row = [title, search_title, volume]
        worksheet.append_row(new_row)
        
        return True
    except Exception as e:
        st.error(f"スプレッドシート書き込みエラー: {e}")
        return False

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

def search_books_with_volume(title, volume_number, min_price=None, max_price=None, retries=3, max_pages=5):
    """
    タイトルで検索し、指定した巻数が含まれる書籍を抽出する
    最大5ページまで検索結果を取得
    APIパラメータ + クライアント側で価格帯に制限（二重チェック）
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
        
        # 価格パラメータを動的に追加
        if min_price is not None:
            params['minPrice'] = min_price
        if max_price is not None:
            params['maxPrice'] = max_price
        
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
                
                # 価格フィルタリング（APIパラメータ + クライアント側での二重チェック）
                item_price = book.get('itemPrice', 0)
                try:
                    price_value = int(item_price) if item_price else 0
                    
                    # 最低価格チェック
                    if min_price is not None and price_value < min_price:
                        continue
                    
                    # 最高価格チェック
                    if max_price is not None and price_value > max_price:
                        continue
                        
                except (ValueError, TypeError):
                    # 価格が不明な場合はスキップ
                    continue
                
                # 条件を満たす書籍を結果に追加
                book_data = {
                    "タイトル": book_title,
                    "ISBN": book["isbn"],
                    "出版日": book["salesDate"],
                    "価格": f"{price_value}円",
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
        
        # 価格設定
        col1, col2 = st.columns(2)
        
        with col1:
            min_price_options = ["指定なし"] + [f"{i}円" for i in range(100, 1100, 100)]
            min_price = st.selectbox(
                "最低価格",
                options=min_price_options,
                help="検索する書籍の最低価格を選択してください"
            )
        
        with col2:
            max_price_options = ["指定なし"] + [f"{i}円" for i in range(500, 2100, 100)]
            max_price = st.selectbox(
                "最高価格",
                options=max_price_options,
                index=6,  # デフォルトで1000円を選択（500から1000までなので6番目）
                help="検索する書籍の最高価格を選択してください"
            )
        
        submitted = st.form_submit_button("🔍 検索開始")
    
    # 検索実行またはセッション状態から検索結果を取得
    if submitted:
        # タイトル必須チェック
        t = title;
        if not t.strip():
            st.error("❌ タイトルを入力してください")
            return
        
        # 価格パラメータの変換
        min_price_value = None
        max_price_value = None
        
        if min_price != "指定なし":
            min_price_value = int(min_price.replace("円", ""))
        
        if max_price != "指定なし":
            max_price_value = int(max_price.replace("円", ""))
        
        # 検索条件の表示
        st.subheader("🔎 検索条件")
        st.write(f"**タイトル:** {title}")
        if volume_number.strip():
            st.write(f"**巻数:** {volume_number}")
        else:
            st.write("**巻数:** 指定なし（全巻表示）")
        
        # 価格条件の表示
        price_condition = []
        if min_price_value is not None:
            price_condition.append(f"{min_price_value}円以上")
        if max_price_value is not None:
            price_condition.append(f"{max_price_value}円以下")
        
        if price_condition:
            st.write(f"**価格:** {' かつ '.join(price_condition)}")
        else:
            st.write("**価格:** 指定なし")
        
        # 検索実行
        with st.spinner("検索中... (最大5ページまで検索します)"):
            results = search_books_with_volume(title.strip(), volume_number.strip(), min_price_value, max_price_value)
        
        # 検索結果をセッション状態に保存
        st.session_state.current_results = results
        st.session_state.current_title = title.strip()
        st.session_state.current_volume = volume_number.strip()
        st.session_state.has_search_results = True
        st.session_state.selected_book_index = 0  # 新しい検索時はリセット
    
    # セッション状態から検索結果を表示
    if st.session_state.get('has_search_results', False) and 'current_results' in st.session_state:
        results = st.session_state.current_results
        
        # 結果表示
        st.subheader("📊 検索結果")
        
        if results:
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True)
            st.success(f"✅ {len(results)}件の書籍が見つかりました！")
            
            # 検索結果の要約（セッション状態から取得）
            current_title = st.session_state.get('current_title', '')
            current_volume = st.session_state.get('current_volume', '')
            
            if current_volume:
                st.info(f"「{current_title}」の{current_volume}巻に関連する書籍を表示しています（最大5ページまで検索）")
            else:
                st.info(f"「{current_title}」に関連する全ての書籍を表示しています（最大5ページまで検索）")
            
            # スプレッドシート追加セクション
            st.subheader("📝 スプレッドシートに追加")
            
            # セッション状態の初期化
            if 'selected_book_index' not in st.session_state:
                st.session_state.selected_book_index = 0
            
            # 選択可能な範囲をチェック
            if st.session_state.selected_book_index >= len(results):
                st.session_state.selected_book_index = 0
            
            # レコード選択（フォーム外で実行）
            book_options = [f"{i+1}. {result['タイトル']}" for i, result in enumerate(results)]
            selected_book_index = st.selectbox(
                "追加する書籍を選択してください",
                options=range(len(results)),
                format_func=lambda x: book_options[x],
                index=st.session_state.selected_book_index,
                help="スプレッドシートに追加したい書籍を選択してください",
                key="book_selector"
            )
            
            # 選択が変更されたらセッション状態を更新
            st.session_state.selected_book_index = selected_book_index
            
            # 選択された書籍の情報を表示
            selected_book = results[selected_book_index]
            st.info(f"選択された書籍: {selected_book['タイトル']}")
            
            # 入力フィールド（フォーム外）
            st.subheader("📋 追加する情報")
            
            # 成功フラグでフィールドをクリア
            clear_fields = st.session_state.get('clear_input_fields', False)
            
            sheet_title = st.text_input(
                "タイトル *（必須）",
                value="" if clear_fields else selected_book['タイトル'],
                help="スプレッドシートに記録するタイトル（必須）",
                key="sheet_title_input"
            )
            
            sheet_search_title = st.text_input(
                "検索用タイトル *（必須）",
                value="" if clear_fields else st.session_state.get('current_title', ''),
                help="検索に使用したタイトル（必須）",
                key="sheet_search_title_input"
            )
            
            sheet_volume = st.text_input(
                "巻数 *（必須）",
                value="" if clear_fields else st.session_state.get('current_volume', ''),
                help="巻数（必須）",
                key="sheet_volume_input"
            )
            
            # クリアフラグをリセット
            if clear_fields:
                st.session_state.clear_input_fields = False
            
            # 成功メッセージの表示
            if st.session_state.get('show_success_message', False):
                st.success("✅ スプレッドシートに追加されました！")
                st.session_state.show_success_message = False
            
            # 追加ボタン
            if st.button("📝 スプレッドシートに追加", key="add_to_sheet_button"):
                # すべての項目が入力されているかチェック
                if not sheet_title.strip():
                    st.error("❌ タイトルを入力してください")
                elif not sheet_search_title.strip():
                    st.error("❌ 検索用タイトルを入力してください")
                elif not sheet_volume.strip():
                    st.error("❌ 巻数を入力してください")
                else:
                    with st.spinner("スプレッドシートに追加中..."):
                        success = add_to_spreadsheet(
                            sheet_title.strip(),
                            sheet_search_title.strip(),
                            sheet_volume.strip()
                        )
                    
                    if success:
                        # 成功時はフィールドクリアフラグと成功メッセージフラグを設定
                        st.session_state.clear_input_fields = True
                        st.session_state.show_success_message = True
                        st.rerun()
                    else:
                        st.error("❌ スプレッドシートへの追加に失敗しました")
        else:
            st.warning("⚠️ 検索条件に一致する書籍は見つかりませんでした")
            
            # 検索のヒント
            st.markdown("""
            **検索のコツ:**
            - タイトルは部分一致で検索され、スペース区切りの単語すべてが含まれる書籍を抽出します
            - 巻数は「108」のように数字のみ入力してください
            - 巻数を指定しない場合、そのタイトルの全ての書籍が表示されます
            - 価格はプルダウンで指定した範囲内の書籍のみ表示されます
            - 最低価格のみ、最高価格のみの指定も可能です
            - 例：「ONE PIECE」と入力すると、「ONE」と「PIECE」両方を含む書籍のみが表示されます
            """)

    # デバッグ情報
    with st.expander("🔧 デバッグ情報"):
        st.write("**API設定状況:**")
        st.write(f"- 楽天API Key: {'✅ 設定済み' if API_KEY else '❌ 未設定'}")
        st.write(f"- 楽天Affiliate ID: {'✅ 設定済み' if AFFILIATE_ID else '❌ 未設定'}")
        st.write(f"- API Endpoint: {API_ENDPOINT}")
        st.write("**Google Sheets設定:**")
        try:
            sheet_name = st.secrets["env"]["sheet_name"]
            st.write(f"- スプレッドシート名: {sheet_name}")
            st.write(f"- Google Cloud認証: {'✅ 設定済み' if 'gcp_service_account' in st.secrets else '❌ 未設定'}")
        except KeyError:
            st.write("- Google Sheets設定: ❌ 未設定")
        st.write("**価格フィルタリング:**")
        st.write("- フィルタリング方法: APIパラメータ + クライアント側二重チェック")
        st.write("- 目的: ユーザー指定価格帯での検索")
        st.write("- 価格設定: 動的（フォームで選択可能）")

if __name__ == "__main__":
    main()
