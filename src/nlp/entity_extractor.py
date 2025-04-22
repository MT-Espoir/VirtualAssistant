from utils.data_loader import DataLoader

# Khởi tạo DataLoader khi module được import
data_loader = DataLoader(language="vi") 
def extract_entities(recognized_text):
    entities = {}
    
    if "turn on" in recognized_text:
        entities['action'] = 'turn_on'
    elif "turn off" in recognized_text:
        entities['action'] = 'turn_off'
    
    return entities

def extract_entities_from_command(command):
    entities = extract_entities(command)
    return entities

def extract_entity(text, intent_type=None):
    """Extract entity (like app name) from the text command"""
    text = text.lower()
    
    # Website extraction
    if intent_type == "website_name":
        # Get websites from JSON data
        common_websites = data_loader.get_website_keywords()
        
        # Look for common website names in the text
        for site, keywords in common_websites.items():
            if any(keyword in text for keyword in keywords):
                return site
        
        # Extract words after open/visit commands
        command_words = data_loader.get_site_commands()
        
        # Try to find the website name after any command word
        for cmd in command_words:
            if cmd in text:
                # Get the text after the command
                after_cmd = text.split(cmd, 1)[1].strip()
                # Remove "website" or "trang" if present
                words_to_remove = ["website", "trang", "web", "site"]
                for word in words_to_remove:
                    after_cmd = after_cmd.replace(word, "").strip()
                return after_cmd.split()[0] if after_cmd else None
    
    # App name extraction
    elif intent_type == "app_name":
        # Get apps from JSON data
        common_apps = data_loader.get_app_keywords()
        
        for app, keywords in common_apps.items():
            if any(keyword in text for keyword in keywords):
                return app
                
        open_commands = data_loader.get_app_commands("open")
        close_commands = data_loader.get_app_commands("close") 
        command_words = open_commands + close_commands
        
        words = text.split()
        for i, word in enumerate(words):
            if word in command_words and i < len(words) - 1:
                return words[i+1]  
                
    return None