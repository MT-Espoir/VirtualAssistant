# import webbrowser
# import urllib.parse
# from utils.data_loader import DataLoader

# # Khởi tạo data loader
# data_loader = DataLoader(language="vi")  # Hoặc lấy ngôn ngữ từ cấu hình

# def search_on_specific_site(query, site):
#     """
#     Tìm kiếm một truy vấn cụ thể trên một trang web được chỉ định.
    
#     Args:
#         query (str): Chuỗi tìm kiếm
#         site (str): Tên trang web ('facebook', 'youtube', etc.)
    
#     Returns:
#         str: Thông báo kết quả
#     """
#     site = site.lower()
#     encoded_query = urllib.parse.quote(query)
    
#     # Lấy URL tìm kiếm từ dữ liệu JSON
#     url_template = data_loader.get_search_url(site)
    
#     if url_template:
#         # Thay thế placeholders trong URL template
#         search_url = url_template.replace("{query}", encoded_query)
#         search_url = search_url.replace("{query_no_spaces}", encoded_query.replace(' ', ''))
        
#         webbrowser.open(search_url)
#         return f"Đang tìm kiếm '{query}' trên {site.title()}"
#     else:
#         # Thử tìm kiếm trực tiếp nếu không có URL được định nghĩa
#         generic_url = f"https://www.{site}.com/search?q={encoded_query}"
#         try:
#             webbrowser.open(generic_url)
#             return f"Đang thử tìm kiếm '{query}' trên {site.title()}"
#         except:
#             return f"Không thể tìm kiếm trên {site}. Trang web không được hỗ trợ."