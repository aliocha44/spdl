import argparse
import os
import requests
import re
import logging
import json
from dataclasses import dataclass
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, error

logging.basicConfig(filename="spdl.log", filemode="a", level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', encoding="utf-8")

CUSTOM_HEADER = {
    'Host': 'api.spotifydown.com',
    'Referer': 'https://spotifydown.com/',
    'Origin': 'https://spotifydown.com',
}

NAME_SANITIZE_REGEX = re.compile(r"[<>:\"\/\\|?*]")

@dataclass(init=True, eq=True, frozen=True)
class Song:
    title: str
    artists: str
    album: str
    link: str

##### FOLDERS AND FILES MANAGEMENT #####

# Check if destination folder already exists
def resolve_path(outpath, playlist_folder=False):
    if not os.path.exists(outpath):
        if not playlist_folder:
            create_folder = input("Directory specified does not exist. Do you want to create it? (y/N): ")
        if playlist_folder or create_folder.lower() == "y":
            os.mkdir(outpath)
        else:
            print("Exiting program")
            exit()

# Check already downloaded tracks
def check_existing_tracks(song_list_dict, outpath):
    existing_tracks = os.listdir(outpath)
    for track in existing_tracks:
        if track.endswith(".mp3"):
            track = track.split(".mp3")[0]
            if song_list_dict.get(track):
                # logging.info(f"{track} already exists in the directory ({outpath}). Skipping download!")
                # print(f"\t{track} already exists in the directory. Skipping download!")
                song_list_dict.pop(track)
    
    return song_list_dict

# Remove empty files
def remove_empty_files(outpath):
    for file in os.listdir(outpath):
        if os.path.getsize(os.path.join(outpath, file)) == 0:
            os.remove(os.path.join(outpath, file))

##### TRACKS DOWNLOAD #####

def attach_cover_art(trackname, cover_art, outpath):
    trackname = re.sub(NAME_SANITIZE_REGEX, "_", trackname)
    filepath = os.path.join(outpath, f"{trackname}.mp3")
    try:
        # raise error("Testing")
        audio = MP3(filepath, ID3=ID3)
    except error as e:
        logging.error(f"Error loading MP3 file from {filepath} --> {e}")
        print(f"\t Error loading MP3 file --> {e}")
        return

    if audio.tags is None:
        try:
            audio.add_tags()
        except error as e:
            logging.error(f"Error adding ID3 tags to {filepath} --> {e}")
            print(f"\tError adding ID3 tags --> {e}")
            return 
        
    audio.tags.add(
        APIC(
            encoding=1,
            mime='image/jpeg',
            type=3,
            desc=u'Cover',
            data=cover_art)
        )
    audio.save(filepath, v2_version=3, v1=2)

def save_audio(trackname, link, outpath):
    trackname = re.sub(NAME_SANITIZE_REGEX, "_", trackname)
    if os.path.exists(os.path.join(outpath, f"{trackname}.mp3")):
        logging.info(f"{trackname} already exists in the directory ({outpath}). Skipping download!")
        print("\t This track already exists in the directory. Skipping download!")
        return False
    
    audio_response = requests.get(link)

    if audio_response.status_code == 200:
        with open(os.path.join(outpath, f"{trackname}.mp3"), "wb") as file:
            file.write(audio_response.content)
        return True

def  get_track_info(link):
    track_id = link.split("/")[-1].split("?")[0]
    response = requests.get(f"https://api.spotifydown.com/download/{track_id}", headers=CUSTOM_HEADER)
    response = response.json()

    return response

def download_track(track_link, outpath, trackname_convention, max_attempts=3):
    resp = get_track_info(track_link)
    if resp['success'] == False:
        print(f"Error: {resp['message']}")
        logging.error(f"Error: {resp['message']}")
        return
    
    trackname = f"{resp['metadata']['title']} - {resp['metadata']['artists']}"
    if trackname_convention == 2:
        trackname = f"{resp['metadata']['artists']} - {resp['metadata']['title']}"

    print(f"Downloading {trackname} to ({outpath})\n")

    for attempt in range(max_attempts):
        try:
            # raise Exception("Testing")
            save_status = save_audio(trackname, resp['link'], outpath)
            # print("Save status: ", save_status)
            if save_status:
                cover_art = requests.get(resp['metadata']['cover']).content
                attach_cover_art(trackname, cover_art, outpath)
            break
        except Exception as e:
            logging.error(f"Attempt {attempt+1} - {trackname} --> {e}")
            print(f"\tAttempt {attempt+1} failed with error: ", e)
    remove_empty_files(outpath)

##### PLAYLIST MANAGEMENT #####

def make_unique_song_objects(track_list, trackname_convention):
    song_list = []
    for track in track_list:
        song_list.append(
            Song(
                title=re.sub(NAME_SANITIZE_REGEX, "_", track['title']),
                artists=re.sub(NAME_SANITIZE_REGEX, "_", track['artists']),
                album=track['album'],
                link=f"https://open.spotify.com/track/{track['id']}"
            )
        )

    # Check duplicates
    trackname_count = {}
    duplicates = []
    unique_song_dict = {}
    for song in song_list:
        trackname = f"{song.artists} - {song.title}"

        if trackname in trackname_count:
            trackname_count[trackname] += 1
        else:
            trackname_count[trackname] = 1
            unique_song_dict[trackname] = song

    # Duplicates based on trackname_count
    duplicates = [song for trackname, song in unique_song_dict.items() if trackname_count[trackname] > 1]

    # Print duplicates found
    if duplicates:
        print(f"Duplicate songs: {len(duplicates)}")
    for song in duplicates:
        if trackname_convention == 1:
            print(f"Duplicate : {song.title} - {song.artists}")
        if trackname_convention == 2:
            print(f"Duplicate : {song.artists} - {song.title}")
    
    return unique_song_dict  

def get_playlist_info(link, trackname_convention):
    
    # Parse URL to get title and creator of playlist
    playlist_id = link.split("/")[-1].split("?")[0]
    response = requests.get(f"https://api.spotifydown.com/metadata/playlist/{playlist_id}", headers=CUSTOM_HEADER)
    response = response.json()
    playlist_name = response['title']
    if response['success']:
        print("-" * 40)
        print(f"Name: {playlist_name} by {response['artists']}")
    
    # Build song list from playlist
    print("Getting songs from playlist (this might take a while ...)")
    track_list = []
    response = requests.get(f"https://api.spotifydown.com/tracklist/playlist/{playlist_id}", headers=CUSTOM_HEADER)
    response = response.json()
    track_list.extend(response['trackList'])

    # Manage large API response
    next_offset = response['nextOffset']
    while next_offset:
        response = requests.get(f"https://api.spotifydown.com/tracklist/playlist/{playlist_id}?offset={next_offset}", headers=CUSTOM_HEADER)
        response = response.json()
        track_list.extend(response['trackList'])
        next_offset = response['nextOffset']

    song_list_dict = make_unique_song_objects(track_list, trackname_convention)

    return song_list_dict, playlist_name

def download_playlist_tracks(playlist_link, outpath, create_folder, trackname_convention, max_attempts=3):
    song_list_dict, playlist_name_old = get_playlist_info(playlist_link, trackname_convention)

    # Chech playlist name to use valid os folder name
    playlist_name = re.sub(NAME_SANITIZE_REGEX, "_", playlist_name_old)
    if (playlist_name != playlist_name_old):
        print(f'\n"{playlist_name_old}" is not a valid folder name. Using "{playlist_name}" instead.')

    # Create folder if needed
    if create_folder == True:
        outpath = os.path.join(outpath, playlist_name)
    
    if os.path.exists(outpath):
        song_list_dict = check_existing_tracks(song_list_dict, outpath)

    if not song_list_dict:
        print(f"\nAll tracks from {playlist_name} already exist in the directory ({outpath}).")
        return
    
    print(f"\nDownloading {len(song_list_dict)} new track(s) from {playlist_name} to ({outpath})")
    print("-" * 40 )

    for index, trackname in enumerate(song_list_dict.keys(), 1):
        print(f"{index}/{len(song_list_dict)}: {trackname}")
        download_track(song_list_dict[trackname].link, outpath, trackname_convention)
            
    remove_empty_files(outpath)

def check_track_playlist(link, outpath, create_folder, trackname_convention):
    resolve_path(outpath)
    # if "/track/" in link:
    if re.search(r".*spotify\.com\/(?:intl-[a-zA-Z]{2}\/)?track\/", link):
        print("\nPlaylist link identified")
        download_track(link, outpath, trackname_convention)

    # elif "/playlist/" in link:
    elif re.search(r".*spotify\.com\/playlist\/", link):
        download_playlist_tracks(link, outpath, create_folder, trackname_convention)

    else:
        logging.error(f"{link} is not a valid Spotify track or playlist link")
        print(f"\n{link} is not a valid Spotify track or playlist link")

##### SYNC MANAGEMENT #####

def sync_playlist_folders(sync_file):
    with open(sync_file, "r") as file:
        data_to_sync = json.load(file)
        # print(data_to_sync)
        set_trackname_convention = 1
        for data in data_to_sync:
            if data.get("convention_code"):
                set_trackname_convention = data["convention_code"]
                continue
            check_track_playlist(data['link'], data['download_location'], data['create_folder'], set_trackname_convention)

def handle_sync_file(sync_file):
    if (os.path.exists(sync_file)):
        print("Syncing local playlist folders with Spotify playlists")
        sync_playlist_folders(sync_file)
        print("-" * 40)
        print("Sync complete!")
    else:
        create_sync_file = input("Sync file does not exist. Do you want to create it? (y/N):")
        if create_sync_file.lower() == "y":
            data_for_sync_file = []
            trackname_type, set_trackname_convention = trackname_convention()
            data_for_sync_file.append(
                {
                    "convention_code": set_trackname_convention,
                    "trackname_convention": trackname_type,
                }
            )
            while True:
                print("-" * 40)
                playlist_link = input("Playlist link (leave empty to finish): ")
                if not playlist_link:
                    break
                create_folder = input("Create a folder for this playlist? (y/N): ")
                download_location = input("Download location for tracks of this playlist (leave empty to default to current directory): ")
                _, playlist_name = get_playlist_info(playlist_link, set_trackname_convention)
                data_for_sync_file.append(
                    {
                        "name": playlist_name,
                        "link": playlist_link,
                        "create_folder": create_folder.lower() == "y",
                        "download_location": download_location if download_location else os.getcwd()
                    }
                )
            with open(sync_file, "w") as file:
                json.dump(data_for_sync_file, file)
            print("Sync file created successfully")
            print("-" * 40)
        else:
            print("Exiting program")
            exit()

def trackname_convention():
    print("How would you like to name the tracks?")
    print("1. Title - Artist")
    print("2. Artist - Title")
    num = int(input("Enter the number corresponding to the naming convention: "))
    if num != 1 and num != 2:
        print("Invalid input. Defaulting to Title - Artist")
        return "Title - Artist", 1
    return "Artist - Title", num

##### MAIN #####

def main():
    # Initialize parser
    parser = argparse.ArgumentParser(description="Program to download tracks from Spotify via CLI")

    # Add arguments
    parser.add_argument("-link", nargs="+", help="URL of the Spotify track or playlist ")
    parser.add_argument("-outpath", nargs="?", default=os.getcwd(), help="Path to save the downloaded track")
    parser.add_argument("-sync", nargs="?", const="sync.json", help="Path of sync.json file to sync local playlist folders with Spotify playlists")
    parser.add_argument("-folder", nargs="?", default=True, help="Create a folder for the playlist(s)")

    args = parser.parse_args()

    if args.sync:
        handle_sync_file(os.path.abspath(args.sync))

    else:
        _, set_trackname_convention = trackname_convention()
        # resolve_path(args.outpath)
        for link in args.link:
            check_track_playlist(link, args.outpath, create_folder=args.folder, trackname_convention=set_trackname_convention)
    
    print("\n" + "-"*25 + " Task complete ;) " + "-"*25 + "\n")

if __name__ == "__main__":
    logging.info("-" * 10 + "Program started" + "-" * 10)
    main()
    logging.info("-" * 10 + "Program ended" + "-" * 10)