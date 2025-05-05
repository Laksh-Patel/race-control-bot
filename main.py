from urllib.request import urlopen
import json
from datetime import datetime, timedelta, timezone
import os
import ast
from functools import lru_cache
import time
from dotenv import load_dotenv
import tweepy

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import logging
import logging.handlers

"""
TODO:
 - Make Selenium tweet mulltiplt things (if there are multiple things to tweet), saves time logging and relogging
 - Make the find_last_session function quicker (hard-coding), so that it wastes less time on github-actions
 - Make the individual code run for 2/3 hours
 - Figure out how often to run the code on Github Actions (every (half) hour?), to not exceed 2000 minutes monthly
 - Edit last_message.txt, and last_error.txt to only be 1 day?, beofore trying to tweet with Tweepy
"""

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger_file_handler = logging.handlers.RotatingFileHandler(
    "status.log",
    maxBytes=1024 * 1024,
    backupCount=1,
    encoding="utf8",
)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger_file_handler.setFormatter(formatter)
logger.addHandler(logger_file_handler)

load_dotenv()

API_KEY = os.environ["API_KEY"]
API_KEY_SECRET = os.environ["API_KEY_SECRET"]
BEARER_TOKEN = os.environ["BEARER_TOKEN"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_ID_SECRET = os.environ["CLIENT_ID_SECRET"]
ACCESS_TOKEN = os.environ["ACCESS_TOKEN"]
ACCESS_TOKEN_SECRET = os.environ["ACCESS_TOKEN_SECRET"]

client = None
api = None

def initialise_twitter_client():
    global client, api
    if client is None or api is None:
        client = tweepy.Client(BEARER_TOKEN, API_KEY, API_KEY_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
        auth = tweepy.OAuth1UserHandler(API_KEY, API_KEY_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
        api = tweepy.API(auth=auth, wait_on_rate_limit=True)

def find_last_session():
    url = "https://api.openf1.org/v1/sessions"
    with urlopen(url) as response:
        sessions = json.load(response)

    now = datetime.now(timezone.utc)

    last_session = sessions[-1]
    
    if last_session.get("session_name") == "Race":
        time_to_run = 3
    else:
        time_to_run = 2

    start_str = last_session.get("date_start")
    if start_str:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        if now - timedelta(hours=time_to_run) <= start <= now:
            return True
        else:
            return False

    return False

HASHTAG_DICT = {
    "Austin": "#USGP",
    "Baku": "#AzerbaijanGP",
    "Catalunya": "#SpanishGP",
    "Hungaroring": "#HungarianGP",
    "Imola": "#ImolaGP",
    "Interlagos": "#BrazilianGP",
    "Jeddah": "#SaudiArabianGP",
    "Las Vegas": "#LasVegasGP",
    "Lusail": "#QatarGP",
    "Melbourne": "#AustralianGP",
    "Mexico City": "#MexicanGP",
    "Miami": "#MiamiGP",
    "Monte Carlo": "#MonacoGP",
    "Montreal": "#CanadianGP",
    "Monza": "#ItalianGP",
    "Sakhir": "#BahrainGP",
    "Shanghai": "#ChineseGP",
    "Silverstone": "#BritishGP",
    "Singapore": "#SingaporeanGP",
    "Spa-Francorchamps": "#BelgianGP",
    "Spielberg": "#AustrianGP",
    "Suzuka": "#JapaneseGP",
    "Yas Marina Circuit": "#AbuDhabiGP",
    "Zandvoort": "#DutchGP",
}

@lru_cache(maxsize=1)
def _all_sessions():
    url = "https://api.openf1.org/v1/sessions"
    response = urlopen(url)
    return json.loads(response.read().decode("utf-8"))

@lru_cache(maxsize=1)
def find_metadata(session_key):
    """
    Given a session_key (int), return (session_name, meeting_name).
    Falls back gracefully if the key isn't found.
    """
    sessions = _all_sessions()
    for s in sessions:
        if s.get("session_key") == session_key:
            hashtag = HASHTAG_DICT.get(s["circuit_short_name"], "#UnknownGP")
            return hashtag, s["session_name"], s["circuit_short_name"]

    raise ValueError(f"session_key {session_key} not found in session list")


def tweet_with_selenium(tweet_texts):
    username = os.environ["TWITTER_USERNAME"]
    password = os.environ["TWITTER_PASSWORD"]

    if not username or not password:
        raise ValueError("Environment variables TWITTER_USERNAME or TWITTER_PASSWORD are missing.")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Required for GitHub Actions
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get("https://twitter.com/login")
        time.sleep(7.5)

        username_input = wait.until(EC.presence_of_element_located((By.NAME, "text")))
        username_input.send_keys(username)
        username_input.send_keys(Keys.RETURN)
        time.sleep(2)

        password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
        password_input.send_keys(password)
        password_input.send_keys(Keys.RETURN)

        wait.until(EC.presence_of_element_located((By.XPATH, '//a[@href="/home"]')))
        
        for tweet_text in tweet_texts:
            tweet_box = wait.until(EC.presence_of_element_located((By.XPATH, '//div[@role="textbox"]')))
            tweet_box.click()
            tweet_box.send_keys(tweet_text)
            time.sleep(1)

            post_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="tweetButtonInline"]')))
            post_button.click()

            time.sleep(5)

    except Exception as e:
        logger.info(f"Error: {e}")
        driver.quit()
        return False
    
    driver.quit()
    return True


def main():

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    txt_path = os.path.join(BASE_DIR, 'last_message.txt')
    with open(txt_path, "r") as f:
        last_message = ast.literal_eval(f.readline())

    date_txt_path = os.path.join(BASE_DIR, 'last_error.txt')
    with open(date_txt_path, "r") as f:
        last_date = f.readline()
    last_date = datetime.strptime(last_date, "%Y-%m-%d")
    today = datetime.today()
    try_tweepy = bool(today - last_date >= timedelta(days=1))

    response = urlopen(f'https://api.openf1.org/v1/race_control?')
    data = json.loads(response.read().decode('utf-8'))[::-1]
    messages = []
    for item in data:
        if item == last_message:
            break
        messages.append(item)

    if not messages:
        logger.info("nothing to tweet")
        return
    
    initialise_twitter_client()

    tweets = []
    for message in messages[::-1]:
        hashtag, session_name, circuit_name = find_metadata(message["session_key"])
        if message["lap_number"]:
            tweet = f'{message["message"]}\n\nLap Number: {message["lap_number"]}\n\n{hashtag} | {session_name} | {circuit_name}'
        else:
            tweet = f'{message["message"]}\n\n{hashtag} | {session_name} | {circuit_name}'
        tweets.append(tweet)

    if try_tweepy:
        try:
            for tweet in tweets:
                client.create_tweet(text=tweet)
                logger.info(f"Tweeted: {tweet}")
            with open(txt_path, "w") as f:
                f.write(f"{messages[0]}")
        except Exception as e:
            date_str = datetime.today().strftime("%Y-%m-%d")
            with open(date_txt_path, "w") as f:
                f.write(date_str)
            r = tweet_with_selenium(tweets)
            if r:
                logger.info(f"Tweeted: {tweets}")
                with open(txt_path, "w") as f:
                    f.write(f"{messages[0]}")
    else:
        r = tweet_with_selenium(tweets)
        if r:
            logger.info(f"Tweeted: {tweets}")
            with open(txt_path, "w") as f:
                f.write(f"{messages[0]}")


tweet_with_selenium(["DEBUG >> TEST"])
logger.info("TWEETED SELENIUM TEST")
quit()

if find_last_session():

    logger.info("ONGOING SESSION")

    start_time = datetime.now()
    while datetime.now() - start_time < timedelta(minutes=10):
        try:
            main()
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(30)
    
else:

    logger.info("NO ONGOING SESSION") 

