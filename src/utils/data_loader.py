import json
import os

class DataLoader:
    def __init__(self, language="en"):
        self.language = language
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        self.websites_data = self._load_data("websites.json")
        self.apps_data = self._load_data("applications.json")
        
    def _load_data(self, filename):
        """Load data from JSON file with language fallback"""
        lang_path = os.path.join(self.data_dir, self.language, filename)
        if os.path.exists(lang_path):
            with open(lang_path, 'r', encoding='utf-8') as file:
                return json.load(file)
        
        # Fall back to default file
        default_path = os.path.join(self.data_dir, filename)
        if os.path.exists(default_path):
            with open(default_path, 'r', encoding='utf-8') as file:
                return json.load(file)
        
        return {}
        
    def get_website_keywords(self):
        """Get the mapping of websites to their keywords"""
        return self.websites_data.get("common_websites", {})
        
    def get_app_keywords(self):
        """Get the mapping of apps to their keywords"""
        return self.apps_data.get("common_apps", {})
        
    def get_search_url(self, site):
        """Get the search URL for a specific site"""
        site = site.lower()
        return self.websites_data.get("search_urls", {}).get(site, "")
        
    def get_site_commands(self):
        """Get the command keywords for website operations"""
        return self.websites_data.get("command_keywords", [])
        
    def get_app_commands(self, command_type="open"):
        """Get the command keywords for app operations"""
        return self.apps_data.get("command_keywords", {}).get(command_type, [])