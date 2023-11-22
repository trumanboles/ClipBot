import irc.client
import os
from collections import deque
import time
import requests

class TwitchBot(irc.client.SimpleIRCClient):
    def __init__(self, channel):
        super().__init__()
        self.channel = channel
        self.broadcaster_id = None
        self.start_time = time.time()
        self.broadcaster_name = os.getenv('BROADCASTER_NAME')
        self.client_id = os.getenv('CLIENT_ID')
        self.message_window = deque()
        self.window_size = 60
        self.total_messages = 0
        self.access_token = os.getenv('ACCESS_TOKEN')
        self.refresh_token = os.getenv('REFRESH_TOKEN')
        self.client_secret = os.getenv('CLIENT_SECRET')
        self.bot_name = os.getenv('BOT_NAME')

    def on_welcome(self, connection, event):
        print("Connected to server. Joining channel.")
        connection.join(self.channel)

    def get_authorization_url(self, redirect_uri, scopes):
        base_url = 'https://id.twitch.tv/oauth2/authorize'
        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(scopes),
            'force_verify': 'true'
        }
        return f"{base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

    def exchange_code_for_tokens(self, code, redirect_uri):
        url = 'https://id.twitch.tv/oauth2/token'
        payload = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri
        }
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            tokens = response.json()
            self.access_token = tokens['access_token']
            self.refresh_token = tokens['refresh_token']
        else:
            raise Exception(f"Failed to exchange code: {response.status_code} - {response.text}")

    def refresh_oauth_token(self):
        url = 'https://id.twitch.tv/oauth2/token'
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }

        response = requests.post(url, data=payload)
        if response.status_code == 200:
            new_tokens = response.json()
            self.access_token = new_tokens['access_token']
            self.refresh_token = new_tokens.get('refresh_token', self.refresh_token)
        else:
            raise Exception(f"Failed to refresh token: {response.status_code} - {response.text}")

    def on_pubmsg(self, connection, event):
        current_time = time.time()
        message = event.arguments[0]
        print(f"{event.source.nick}: {event.arguments[0]}")

        self.total_messages += 1
        self.message_window.append((message, current_time))
        self.clean_old_messages(current_time)

        time_elapsed = (current_time - self.start_time) / 60
        average_frequency = self.total_messages / time_elapsed if time_elapsed > 0 else 0

        current_frequency = len(self.message_window) / (self.window_size / 60)

        trigger_threshold = average_frequency * 1.5

        print(f"Average frequency: {average_frequency} messages/minute")
        print(f"Current frequency: {current_frequency} messages/minute")
        print(f"Trigger threshold: {trigger_threshold} messages/minute")

        if current_frequency > trigger_threshold:
            self.create_clip()

    def clean_old_messages(self, current_time):
        while self.message_window and current_time - self.message_window[0][1] > self.window_size:
            self.message_window.popleft()

    def fetch_broadcaster_id(self, streamer_username):
        url = f"https://api.twitch.tv/helix/users?login={streamer_username}"
        headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {self.access_token}'
        }

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            user_data = response.json()
            self.broadcaster_id = user_data['data'][0]['id']
            print(f"Fetched broadcaster ID: {self.broadcaster_id}")
        elif response.status_code == 401:
            print("Token expired. Attempting to refresh.")
            self.refresh_oauth_token()
            headers['Authorization'] = f'Bearer {self.access_token}'
            response = requests.get(url, headers=headers)
        else:
            print(f"Error fetching broadcaster ID: {response.status_code}")
            self.broadcaster_id = None

    def start(self):
        self.refresh_oauth_token()
        self.fetch_broadcaster_id(self.broadcaster_name)

        if self.broadcaster_id is None:
            print("Failed to fetch broadcaster ID. Exiting.")
            return
        try:
            print("Connecting to Twitch IRC...")
            oauth_token = f"oauth:{self.access_token}"
            self.connect("irc.chat.twitch.tv", 6667, self.bot_name, oauth_token)
            self.reactor.process_forever()
        except irc.client.ServerConnectionError as e:
            print(f"Error connecting: {e}")

    def create_clip(self):
        url = "https://api.twitch.tv/helix/clips"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Client-Id': self.client_id
        }
        payload = {'broadcaster_id': self.broadcaster_id}

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 202:
            clip_data = response.json()
            clip_url = clip_data['data'][0]['edit_url']
            print(f"Clip created: {clip_url}")
            return clip_url
        else:
            print(f"Failed to create clip: {response.status_code}")
            print(f"Response: {response.text}")
            return None