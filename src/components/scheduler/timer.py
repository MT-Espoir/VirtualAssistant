from datetime import datetime, date
import json
import os

class Date_Tracker:
    """Class to manage time for whole system"""
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or os.path.dirname(__file__)
        self.daily_data = []
        self.last_reset_day = None
    
    def is_new_day(self):
        """check if the current day is different from the last reset day"""
        today = date.today()
        if self.last_reset_day is None or today != self.last_reset_day:
            return True
        return today != self.last_reset_day
    
    def reset_daily_data(self):
        if self.is_new_day():
            self.daily_data.clear()
            self.last_reset_day = date.today()
            return True
        return False
    
    def add_daily_item(self, item):
        """Add data to the daily data list"""
        self.reset_daily_data()
        if item not in self.daily_data:
            self.daily_data.append(item)
            return True
        return False
    