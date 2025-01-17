import os
import base64
import json
import requests
import random
import urllib.parse
from datetime import datetime #avoid datetime has no attribute now error
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from flask import Flask, redirect, request, jsonify, session


#python3 -m venv chatbot
#source chatbot/bin/activate


load_dotenv()
client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")

authorization_url =  ""
auth_url = "https://accounts.spotify.com/authorize"
redirect_uri = "http://localhost:5000/callback"
token_url = "https://accounts.spotify.com/api/token"
scope = "user-read-private user-read-email playlist-modify-private"






app = Flask(__name__)
app.secret_key = "77846d-bbbggaaa3-2828-9dfttg"


@app.route('/')
def index():
    return "Welcome to MusiWrite! <a href='/login'> Login with Spotify </a>"


@app.route('/login')
def login():

 

    params = {

        'client_id': client_id,
        'response_type': 'code', 
        'scope': scope,
        'redirect_uri': redirect_uri,
        'show_dialog': True

    }

    authorization_url = f"{auth_url}?{urllib.parse.urlencode(params)}"
    return redirect(authorization_url)
    

@app.route('/callback')
def callback():
    if 'error' in request.args:
        return jsonify({"error": request.args['error']})

    if 'code' in request.args:
        req_body = {
            'code': request.args['code'],
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret
        }
    response = requests.post(token_url, data=req_body)
    token_info = response.json()
    
    session['access_token'] = token_info['access_token']
    session['refresh_token'] = token_info['refresh_token']
    session['expires_at'] = datetime.now().timestamp() + token_info['expires_in']

    return redirect('/input-text')


@app.route('/refresh-token')
def refresh_token():
    if 'refresh_token' not in session:
        return redirect('/login')
    
    if datetime.now().timestamp() > session['expires_at']:
        req_body = {
            'grant_type': 'refresh_token',
            'refresh_token': session['refresh_token'],
            'client_id': client_id,
            'client_secret': client_secret
        }

        response = requests.post(token_url, data=req_body)
        new_token_info = response.json()

        session['access_token'] = new_token_info['access_token']
        session['expires_at'] = datetime.now().timestamp() + new_token_info['expires_in']
        return redirect('/run-backend')


@app.route('/input-text', methods=['GET'])
def input_text():
    return '''
    <form action="/process-text" method="POST">
            <label for="story_text">Enter your story text:</label><br>
            <textarea id="story_text" name="story_text" rows="4" cols="50"></textarea><br><br>
            <label for="genre">Enter a genre:</label><br>
            <input type="text" id="genre" name="genre"><br><br>
            <button type="submit">Submit</button>
    </form>
'''

@app.route('/process-text', methods=['POST'])
def process_text():
    
    session['story_text'] = request.form['story_text'] 
    session['genre'] = request.form['genre'].strip()

     
    
    
    return redirect('/run-backend')

@app.route('/run-backend')
def run_backend():

    if 'access_token' not in session:
        return redirect('/login')
    
    if datetime.now().timestamp() > session['expires_at']:
        return redirect('/refresh-token')
    
    story_text = session['story_text']
    genre = session['genre']
    access_token = session['access_token']
    token = get_token()
    user_id = get_user_id(access_token)




    response = handle_conversation(genre, story_text)
    print(response)

    if len(response) == 2:
            descriptor, title = response[0], response[1]
            print(descriptor + " " + title)
            result = search_for_playlist(token, descriptor)

    
    else:
        descriptor, genre, title = response[0], response[1], response[2]
        print(descriptor + " " + genre + " " + title)

        result = search_for_playlist(token, descriptor + " "+ genre)


 
    playlists = []
    song_list = []
    
    playlist_id = make_user_playlist(access_token, user_id, title)
    print("PLAYLIST ID: " + playlist_id)
    try:
        for i in range(len(result)):
            playlists.append(result[i]["id"])
            song_list.extend(get_playlist_songs(token, result[i]["id"]))
            print(song_list)


    

    except:
        print("No playlist.")

     
    populate_playlist(access_token, playlist_id, song_list)

    return "Done!"

 



template = """


 
You are given a story text, and a genre. The user wants to find songs related to the story text that are in that genre.
An example might be: Adam stood up, the sun calmly shining down on him. genre: Rock. You would analyze the text, and find a word to describe it, then add the genre and finally the title. You want to seperate the words with commas.
So your response could be: Calm, Rock, Title
Only output three things: a descriptor (one word), the genre the user gave you, and the title of the playlist.
Do not write anything else. If the user has not given you a genre, do not output a genre. So for example,
if you were just given story text like this: His heart was racing, he didn't know what to do. With no genre following it, you could write: "Exciting", followed by a title like "Exhilerating Playlist". You would not add a genre to it.
The playlist title needs to match the text well. For example, if there is a fight scene with a protagonist named Malrik barely surviving, you could title it "Malrik's Vengeance" or something cool like that.
Sample output: Violent, Rap, Malrik's Vengeance

The user wants this to be the genre: {genre}

Here is the story text: {story_text}

Answer:



"""


#You are to give three criteria related to the text that would match the song. These three are:

# -Energy (0.0 to 1.0): perceptual measure of intensity and activity. Typically, energetic tracks feel fast, loud, and noisy. For example, death metal has high energy, while a Bach prelude scores low on the scale.
# For example, a fight scene might have tags that relate to a more upbeat, aggressive song whereas calmer scenes would have tags that correspond to more serene music.
 
# -Valence (0.0 to 1.0): Describing the musical positiveness conveyed by a track. Tracks with high valence sound more positive (e.g. happy, cheerful, euphoric), while tracks with low valence sound more negative (e.g. sad, depressed, angry).

# -Loudness (-60 to 0): The overall loudness of a track in decibels (dB). Loudness values are averaged across the entire track and are useful for comparing relative loudness of tracks. Loudness is the quality of a sound that is the primary psychological correlate of physical strength (amplitude). Values typically range between -60 and 0 db.

# Using the text, you will match it to those 3 song qualities. For example, a fight scene would have high energy, low valence, and relatively high loudness. 
# However, if it is a calm scene, you would give it lower energy, higher valence, and lower relative loudness.

# Your answer will be in the form: Energy,valence,Loudness. For example, 0.9,0.1,-5
# Do not write anything else. Do not write, for example: Energy: 0.9 . Just write 0.9 instead. Do not write anything else. Just those three values.
# You are only to write three values corresponding to the text. These values can change, but you must only output those three values.

model = OllamaLLM(model = "llama3")
prompt = ChatPromptTemplate.from_template(template)
chain = prompt | model


def handle_conversation(genre, story_text):

     
        
    result = chain.invoke({"genre": genre, "story_text": story_text }).strip().split(',')
    
    print("AI:", result)
    
    return result
    
        





 
def get_token():
    auth_string = client_id + ":" + client_secret
    auth_bytes = auth_string.encode("utf-8")
    auth_base64 = str(base64.b64encode(auth_bytes), "utf-8")

    url = token_url
    headers = {
        "Authorization": "Basic " + auth_base64, 
        "Content-Type": "application/x-www-form-urlencoded"

    }
    data = {"grant_type": "client_credentials"}
    result = requests.post(url, headers=headers, data=data)
    json_result = json.loads(result.content)
    token = json_result["access_token"]
    return token




def get_auth_header(token):
    return {"Authorization": "Bearer " + token}



def get_authorization_url(client_id, redirect_uri, scope):

    base_url = auth_url


    params = {
        "response_type": "code",   
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": "some_random_state"   
    }
    
    response = requests.get(base_url, params=params)
    
    return response.url

 




def search_for_playlist(token, playlist_name):
    url = "https://api.spotify.com/v1/search"
    headers = get_auth_header(token)
    query = f"?q={playlist_name}&type=playlist&limit=3&market=US"

    query_url = url + query
    result = requests.get(query_url, headers=headers)
    json_result = json.loads(result.content)["playlists"]["items"]
 
    if len(json_result) == 0:
        print("No playlist with this name exists...")
        return None
    
    results = []

    for i in range(len(json_result)):
        results.append(json_result[i])
    
    return results


def get_playlist_songs(token, playlist_id):
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    headers = get_auth_header(token)
    result = requests.get(url, headers=headers)
    json_result = json.loads(result.content)["items"]


    song_names = []
    for item in json_result:
        song_names.append(item["track"]["id"])

    
 

    if len(song_names) < 20:
        random_songs = song_names
    else:
        random_songs = (random.sample(song_names,20))
 

    return random_songs


def get_user_id(access_token):
    

    url = "https://api.spotify.com/v1/me"
    headers = get_auth_header(access_token)
    result = requests.get(url, headers=headers)
    json_result = json.loads(result.content)
    user_id = json_result["id"]
    return user_id

def make_user_playlist(access_token, user_id, title):

    url = f"https://api.spotify.com/v1/users/{user_id}/playlists"
    headers = get_auth_header(access_token)

    data = {
        "name": title,  
        "description": "Made with MusiWrite",   
        "public": False
    }
    
    response = requests.post(url, headers=headers, json=data)
    json_result = response.json()
    playlist_id = json_result["id"]

    return playlist_id

def populate_playlist(access_token, playlist_id, song_list):
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    headers = get_auth_header(access_token)
    uris = [f"spotify:track:{song}" for song in song_list]
    data = {"uris": uris}
    response = requests.post(url, headers=headers, json=data)

 

    
    
    



 









    
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
    #handle_conversation()

 

 