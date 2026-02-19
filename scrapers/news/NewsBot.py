import requests 
import os
import time 
from datetime import datetime 
import schedule
from dotenv import load_dotenv


load_dotenv()


MARKETAUX_TOKEN = os.getenv("MARKETAUX_TOKEN")
MARKETAUX_URL = "https://api.marketaux.com/v1/"

class NewsBot():
    def __init__(self, token, stocks, start_time:str, end_time:str, frequency=5):
        """
        token (str): API token for authentication
        stocks (list): A list of stock symbols to monitor
        frequency (float): Frequency in minutes to check for news updates
        """
        self.stocks = stocks 
        self.frequency = frequency
        self.token = token
        
        # Process the times to be between
        self.start_time = datetime.strptime(start_time, "%H:%M").time()
        self.end_time = datetime.strptime(end_time, "%H:%M").time()
        
        # For choosing times, we want more recent articles first
        self.recency = 'day'
        self.timeframe = 'today'  # Idk edit this later
        
        
    def fetch_news(self):
        response = requests.get(MARKETAUX_URL + 'news/all', params={'api_token': self.token, 'symbols': ','.join(self.stocks), })
        
        # Need to test and figure out what I am doing with this data
        if response.status_code == 200:
            data = response.json()
            print(data)
        
        
    def run(self):
        schedule.every(self.frequency).minutes.do(self.fetch_news)
        
        # While between the current times 
        while datetime.now().time() >= self.start_time and datetime.now().time() <= self.end_time:
            schedule.run_pending()
            time.sleep(15)
            
            
# Sample use
if __name__ == "__main__":
    stocks = os.getenv("STOCKS").split(",")
    news_bot = NewsBot(token=MARKETAUX_TOKEN, stocks=stocks, start_time="09:30", end_time="16:00", frequency=5)
    news_bot.run()