#!/usr/bin/python

import time
import sys
import os
import json
import requests
from bs4 import BeautifulSoup
from mastodon import Mastodon
from datetime import datetime
# import re
# from unidecode import unidecode
import sqlite3
from urllib.parse import urlparse, parse_qs, quote
from pprint import pprint


# I'm particular about my time format
def get_time():
    # Get the current time
    current_time = datetime.now().strftime("%l:%M %p")
    # Extract hours and minutes
    hours_minutes = current_time[:-3]
    # Get am/pm indicator
    am_pm = current_time[-2].lower()
    return f"{hours_minutes}{am_pm}"


# Writes the state file
def write_state(file_path, id):
    with open(file_path, 'w') as file:
        file.write(id.strip())
    return


# Reads the state from teh state file
def read_state(file_path):
    try:
        with open(file_path, 'r') as file:
            state = file.readline().strip()  # Read the first line and remove leading/trailing whitespace
    # If it fails, we don't have a state file yet. So make one.
    # This assumption is possibly dangerous. Time will tell.
    except:
        state = "starting up"
        write_state(file_path, state)
    return state


# Write playlist item into database
def write_database(song, db_file):
    # Connect to SQLite database (creates a new DB if it doesn't exist)
    conn = sqlite3.connect(db_file)
    # Create a cursor object to interact with the database
    cursor = conn.cursor()
    # Create a table to store datetime
    cursor.execute('''CREATE TABLE IF NOT EXISTS playlist (
                        id INTEGER PRIMARY KEY,
                        datetime_column DATETIME,
                        playlist_id TEXT,
                        dj TEXT,
                        song TEXT,
                        artist TEXT,
                        album TEXT,
                        album_art TEXT
                        )''')
    # Get current datetime
    current_datetime = datetime.now()
    # Create Insert Statement
    sql = 'INSERT INTO playlist (datetime_column, playlist_id, dj, song, artist, album, album_art) VALUES (?, ?, ?, ?, ?, ?, ?)'
    # Insert current datetime into the table
    cursor.execute(sql, (current_datetime, song["id"], '', song['trackName'], song['artistName'], song['collectionName'], song['itunes_link']))
    # Commit changes and close connection
    conn.commit()
    conn.close()
    return


# Loads the configuration file. Do all config in ./config/config.json & exclude from repo.
def get_config(working_directory):
    try:
        with open(working_directory + '/config/config.json', 'r') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        print("Config file not found.")
    except json.JSONDecodeError as e:
        print(f"JSON decoding error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")


def get_current_song(playlist_url):
    current_song = {}
    # Get the playlist HTML from KUVO
    response = requests.get(playlist_url)
    # Check if the request was successful (status code 200)
    # pprint(response.content)
    if response.status_code == 200:
        # Parse the content using BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        spin_item = soup.find('a', class_='itunes-link')
        print("\nAnchor tag:\n" + str(spin_item))
        print(".get(href):\n" + str(spin_item.get('href'))) # fer debuggin'
        # Parse the URL
        # Check if there's a current song playing:
        if spin_item is None:
            current_song["is_song"] = False
            current_song["id"] = "Not A Song"
        else:
            itunes_link = str(spin_item.get('href'))
            parsed_url = urlparse(itunes_link)
            # print(f"parsed_url: {parsed_url}")
            # Get the query parameters as a dictionary
            current_song = parse_qs(parsed_url.query)
            current_song["is_song"] = True
            # These are parsing as lists, for some reason. There's probably a cleaner way to conver to strings.
            if "artistName" in current_song and "trackName" in current_song and "collectionName" in current_song:
                current_song["artistName"] = current_song["artistName"][0].strip()
                # Sometimes they parse as nested lists. Why?
                if isinstance(current_song["artistName"], list):
                    print(current_song["artistName"] + " is still a list.")
                    current_song["artistName"] = current_song["artistName"][0].strip()
                current_song["trackName"] = current_song["trackName"][0].strip()
                if isinstance(current_song["trackName"], list):
                    print(current_song["trackName"] + " is still a list.")
                    current_song["trackName"] = current_song["trackName"][0].strip()
                current_song["collectionName"] = current_song["collectionName"][0].strip()
                if isinstance(current_song["collectionName"], list):
                    print(current_song["collectionName"] + " is still a list.")
                    current_song["collectionName"] = current_song["collectionName"][0].strip()
                current_song["itunes_link"] = itunes_link
                current_song["id"] = current_song["trackName"] + current_song["artistName"]
                current_song["cover_art_available"] = True
            else:
                current_song["is_song"] = False
                current_song["id"] = "Not A Song"
                current_song["cover_art_available"] = False

        return current_song


def get_artwork_link_from_apple(itunes_link):
    # We're following the "Buy on iTunes" link to snag the artwork from Apple.
    response = requests.get(itunes_link)
    thumbnail_url = ""
    if response.status_code == 200:
        # Parse the content using BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        # Find the script object on the page with the song data.
        itunes_metadata = soup.find('script', id='schema:song')
        # pprint(itunes_metadata) # fer debuggin'
        # Parse that sucker
        if itunes_metadata is not None:
            song_data = json.loads(itunes_metadata.get_text(strip=True))
            thumbnail_url = song_data["audio"]["audio"]["thumbnailUrl"]
        else:
            print("No <script id=schema:song> in HTML")
    return thumbnail_url


# Your standard posting to Mastodon function
def post_to_mastodon(current_song, server, access_token):
    # Create an app on your Mastodon instance and get the access token
    mastodon = Mastodon(
        access_token=access_token,
        api_base_url=server
    )
    # Text content to post
    text_to_post = current_song["time"] + " " + current_song["trackName"] + " by " + current_song["artistName"] + " from " + current_song["collectionName"]
    # text_to_post += "\n" + make_hashtags(current_song["artistName"], current_song["trackName"], current_song["dj"], config["hashtags"])
    # print(text_to_post)
    alt_text = "An image of the cover of the record album '" + current_song["collectionName"] + "' by " + current_song["artistName"]

    # Check if there's an image included. If there is, post it
    if current_song["cover_art_available"]:
    # URL of the image you want to attach
        image_data = requests.get(current_song["itunes_artwork_url"]).content
        # Upload the image and attach it to the status
        media = mastodon.media_post(image_data, mime_type='image/jpeg', description=alt_text)
        # Post the status with text and image attachment
        mastodon.status_post(status=text_to_post, media_ids=[media['id']], visibility="public")
    else:
        mastodon.status_post(status=text_to_post, visibility="public")
    print(f"***** Posted ID: {current_song['trackName']} by {current_song['artistName']} to Mastodon at {formatted_datetime}")
    return


def check_playlist_and_post():
    # Get the information about the current song playing
    current_song = get_current_song(config["playlist_url"])
    state_file = working_directory + "/state"
    # Get the latest ID written to the state file
    last_post = read_state(state_file)
    current_song['time'] = get_time()
    # Check if we've already posted this song by comparing the ID we recieved from the scrape
    # with the one in the state file
    if current_song["id"] != last_post and current_song["is_song"]:
        # Make sure we got a good scrape of playlist page
        if current_song["id"] == "notfound":
            print(f"***** Latest song not found.  {formatted_datetime}")
        else:
            if current_song["cover_art_available"]:
                # Follow the iTunes link to get a URL for the artwork. Stick it into current_song{}
                thumbnail_url = get_artwork_link_from_apple(current_song["itunes_link"])
                if len(thumbnail_url) > 10:

                    current_song["itunes_artwork_url"] = thumbnail_url
                else:
                    # This is catching the situation where we have a false iTunes link from KJAC.
                    # We may want to abort the posting entirely at this point. This is one of their
                    # "Voice" songs, sometimes it's "Comp". Basically, it's announcer stuff, not music.
                    # Unset thumbnail URL in a way that won't crash if it's not there
                    current_song.pop('thumbnail_url', None)
                    current_song["cover_art_available"] = False

            post_to_mastodon(current_song, config["mastodon_server"], config["mastodon_access_token"])
            write_state(state_file, current_song["id"])
            write_database(current_song, working_directory + "/" + config["database"])
    else:
        print(f"***** Song: {current_song['trackName']} skipped. {formatted_datetime}")





# Setup Global Variables:
# Get the current date and time
current_datetime = datetime.now()
formatted_datetime = current_datetime.strftime("%A, %B %d, %Y %I:%M:%S %p")
if len(sys.argv) > 1:
    working_directory = sys.argv[1]
    print (f"{working_directory} provided")
    config = get_config(working_directory)
else:
    print("No working directory argument provided. Exiting.\n")
    sys.exit()

for i in range(0, config["times_to_poll_per_minute"] - 1):
    check_playlist_and_post()
    # Don't sleep after the last run 
    if i < (config["times_to_poll_per_minute"] - 1):
        time.sleep(60 / config["times_to_poll_per_minute"])

# Iterate
# while True:
    # # Get the information about the current song playing
    # current_song = get_current_song(config["playlist_url"])
    # state_file = working_directory + "/state"
    # # Get the latest ID written to the state file
    # last_post = read_state(state_file)
    # # Get the current date and time
    # current_datetime = datetime.now()
    # formatted_datetime = current_datetime.strftime("%A, %B %d, %Y %I:%M:%S %p")
    # current_song['time'] = get_time()
    # # Check if we've already posted this song by comparing the ID we recieved from the scrape
    # # with the one in the state file
    # if current_song["id"] != last_post and current_song["is_song"]:
    #     # Make sure we got a good scrape of playlist page
    #     if current_song["id"] == "notfound":
    #         print(f"***** Latest song not found.  {formatted_datetime}")
    #     else:
    #         if current_song["cover_art_available"]:
    #             # Follow the iTunes link to get a URL for the artwork. Stick it into current_song{}
    #             thumbnail_url = get_artwork_link_from_apple(current_song["itunes_link"])
    #             if len(thumbnail_url) > 10:
    # 
    #                 current_song["itunes_artwork_url"] = thumbnail_url
    #             else:
    #                 # This is catching the situation where we have a false iTunes link from KJAC.
    #                 # We may want to abort the posting entirely at this point. This is one of their
    #                 # "Voice" songs, sometimes it's "Comp". Basically, it's announcer stuff, not music.
    #                 # Unset thumbnail URL in a way that won't crash if it's not there
    #                 current_song.pop('thumbnail_url', None)
    #                 current_song["cover_art_available"] = False
    #                 
    #             
    #         post_to_mastodon(current_song, config["mastodon_server"], config["mastodon_access_token"])
    #         write_state(state_file, current_song["id"])
    #         write_database(current_song, working_directory + "/" + config["database"])
    # else:
    #     print(f"***** Song: {current_song['trackName']} skipped. {formatted_datetime}")


    # sys.exit() # stop it here for debugging
    # time.sleep(config["frequency"])
