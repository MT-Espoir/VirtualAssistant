import webbrowser
import urllib.parse
import requests
from bs4 import BeautifulSoup
from utils.data_loader import DataLoader

# Khởi tạo data loader
data_loader = DataLoader(language="vi")  # Hoặc lấy ngôn ngữ từ cấu hình

def search_web(query, engine="google"):
    """
    Tìm kiếm web với truy vấn được chỉ định
    
    Args:
        query: Từ khóa tìm kiếm
        engine: Công cụ tìm kiếm (google, bing, youtube, etc.)
    """
    if not query:
        return "No search query provided"
        
    # Mã hóa truy vấn tìm kiếm
    encoded_query = urllib.parse.quote(query)
    
    # Xác định URL tìm kiếm dựa trên công cụ
    if engine.lower() == "google":
        url = f"https://www.google.com/search?q={encoded_query}"
    elif engine.lower() == "bing":
        url = f"https://www.bing.com/search?q={encoded_query}"
    elif engine.lower() == "youtube":
        url = f"https://www.youtube.com/results?search_query={encoded_query}"
    else:
        url = f"https://www.google.com/search?q={encoded_query}"
    
    # Mở trình duyệt mặc định với URL
    webbrowser.open(url)
    
    return f"Searching for '{query}' on {engine}"

def search_on_specific_site(query, site):
    """
    Tìm kiếm một truy vấn cụ thể trên một trang web được chỉ định.
    
    Args:
        query (str): Chuỗi tìm kiếm
        site (str): Tên trang web ('facebook', 'youtube', etc.)
    
    Returns:
        str: Thông báo kết quả
    """
    site = site.lower()
    encoded_query = urllib.parse.quote(query)
    
    # Lấy URL tìm kiếm từ dữ liệu JSON
    url_template = data_loader.get_search_url(site)
    
    if url_template:
        # Thay thế placeholders trong URL template
        search_url = url_template.replace("{query}", encoded_query)
        search_url = search_url.replace("{query_no_spaces}", encoded_query.replace(' ', ''))
        
        webbrowser.open(search_url)
        return f"Đang tìm kiếm '{query}' trên {site.title()}"
    else:
        # Thử tìm kiếm trực tiếp nếu không có URL được định nghĩa
        generic_url = f"https://www.{site}.com/search?q={encoded_query}"
        try:
            webbrowser.open(generic_url)
            return f"Đang thử tìm kiếm '{query}' trên {site.title()}"
        except:
            return f"Không thể tìm kiếm trên {site}. Trang web không được hỗ trợ."

def open_website(site_name):
    """
    Mở trực tiếp một trang web cụ thể
    
    Args:
        site_name: Tên trang web cần mở
    """
    # Danh sách các trang web phổ biến
    popular_sites = {
        "youtube": "https://www.youtube.com",
        "facebook": "https://www.facebook.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "twitter": "https://twitter.com",
        "instagram": "https://www.instagram.com",
        "linkedin": "https://www.linkedin.com",
        "github": "https://github.com",
        "netflix": "https://www.netflix.com",
        "amazon": "https://www.amazon.com",
        "reddit": "https://www.reddit.com",
        "wikipedia": "https://www.wikipedia.org",
        "tiktok": "https://www.tiktok.com",
        "spotify": "https://www.spotify.com",
        "twitch": "https://www.twitch.tv",
    }
    
    # Tìm website trong danh sách
    site_name = site_name.lower().strip()
    if site_name in popular_sites:
        webbrowser.open(popular_sites[site_name])
        return f"Opening {site_name}"
    else:
        # Thử mở trang web với tên miền phổ biến
        if "." not in site_name:
            url = f"https://www.{site_name}.com"
        else:
            url = f"https://{site_name}"
        
        webbrowser.open(url)
        return f"Trying to open {url}"

def search_and_play_youtube(query):
    """
    Tìm kiếm và mở video đầu tiên trên YouTube theo từ khóa
    
    Args:
        query: Từ khóa tìm kiếm video
    """
    if not query:
        return "No search query provided"
    
    try:
        # Mã hóa truy vấn tìm kiếm
        encoded_query = urllib.parse.quote(query)
        
        # URL trực tiếp để phát video đầu tiên (thử nghiệm)
        url = f"https://www.youtube.com/search?q={encoded_query}&sp=EgIQAQ%253D%253D"
        
        # Mở trình duyệt mặc định với URL
        webbrowser.open(url)
        
        import threading
        import time
        
        def try_direct_video():
            time.sleep(1.5) 
            url2 = f"https://www.youtube.com/results?search_query={encoded_query}&sp=EgIQAQ%253D%253D"
            webbrowser.open(url2)
        
        return f"Đang tìm và phát video '{query}' trên YouTube"
    
    except Exception as e:
        return f"Có lỗi khi tìm kiếm trên YouTube: {str(e)}"

def search_and_play_youtube_direct(query):
    """
    Tìm kiếm trực tiếp và mở video đầu tiên trên YouTube theo từ khóa
    Phương pháp này sẽ tìm trực tiếp video ID đầu tiên và phát nó
    
    Args:
        query: Từ khóa tìm kiếm video
    """
    if not query:
        return "No search query provided"
    
    try:
        # Cài đặt pytube nếu chưa có
        try:
            from pytube import Search
            
            # Tìm kiếm video
            s = Search(query)
            s.results  # Thực hiện tìm kiếm
            
            # Lấy video đầu tiên
            if len(s.results) > 0:
                first_video = s.results[0]
                video_url = f"https://www.youtube.com/watch?v={first_video.video_id}"
                
                # Mở URL video
                webbrowser.open(video_url)
                return f"Đang phát video '{first_video.title}'"
            else:
                return f"Không tìm thấy video nào cho '{query}'"
                
        except ImportError:
            # Nếu không có pytube, sử dụng phương pháp URL trực tiếp
            encoded_query = urllib.parse.quote(query)
            url = f"https://www.youtube.com/results?search_query={encoded_query}"
            webbrowser.open(url)
            return f"Đang tìm kiếm '{query}' trên YouTube (cần cài pytube để phát tự động)"
    
    except Exception as e:
        return f"Có lỗi khi tìm kiếm trên YouTube: {str(e)}"