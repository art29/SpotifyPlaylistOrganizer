from urllib.parse import urlencode
import requests
from flask import Flask, render_template, request, session, url_for, redirect, jsonify, abort, make_response
import json
import random
import string
import time
import secrets
import config

app = Flask(__name__, template_folder='templates')
app.secret_key = 'development'

CLIENT_ID = config.id
CLIENT_SECRET = config.secret
REDIRECT_URI = "http://localhost:5000/callback"
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'


@app.route('/')
def index():
    state = ''.join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16)
    )

    payload = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'state': state,
        'scope': 'playlist-modify-private playlist-read-private playlist-read-collaborative',
        'show_dialog': True,
    }

    res = make_response(redirect(f'{AUTH_URL}/?{urlencode(payload)}'))
    res.set_cookie('spotify_auth_state', state)

    return res


@app.route('/logout')
def logout():
    state = ''.join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16)
    )

    payload = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'state': state,
        'scope': 'playlist-modify-private playlist-read-private playlist-read-collaborative',
    }

    res = make_response(redirect(f'{AUTH_URL}/?{urlencode(payload)}'))
    res.set_cookie('spotify_auth_state', state)

    return res


@app.route('/callback')
def callback():
    error = request.args.get('error')
    code = request.args.get('code')
    state = request.args.get('state')
    stored_state = request.cookies.get('spotify_auth_state')

    if state is None or state != stored_state:
        app.logger.error('Error message: %s', repr(error))
        app.logger.error('State mismatch: %s != %s', stored_state, state)
        abort(400)

    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
    }

    res = requests.post(TOKEN_URL, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
    res_data = res.json()

    if res_data.get('error') or res.status_code != 200:
        app.logger.error(
            'Failed to receive token: %s',
            res_data.get('error', 'No error information received.'),
        )
        abort(res.status_code)

    session['tokens'] = {
        'access_token': res_data.get('access_token'),
        'refresh_token': res_data.get('refresh_token'),
    }

    return redirect(url_for('choose_playlist'))


@app.route('/refresh')
def refresh():
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': session.get('tokens').get('refresh_token'),
    }

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    res = requests.post(
        TOKEN_URL, auth=(CLIENT_ID, CLIENT_SECRET), data=payload, headers=headers
    )

    res_data = res.json()

    session['tokens']['access_token'] = res_data.get('access_token')

    return json.dumps(session['tokens'])


@app.route('/choose_playlist')
def choose_playlist():
    if 'tokens' not in session:
        app.logger.error('No tokens in session.')
        abort(400)

    token = session.get('tokens').get('access_token')

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
    }

    playlists = {}

    response = requests.get('https://api.spotify.com/v1/me', headers=headers)
    user_id = response.json()['id']

    url = 'https://api.spotify.com/v1/users/' + user_id + '/playlists'

    response = requests.get(url, headers=headers)

    offset = 0
    next_list = True

    while next_list:
        for i in response.json()['items']:
            playlist = str(i['name'])
            playlist_id = str(i['id'])
            playlists[playlist_id] = playlist
        if response.json()['next'] is not None:
            offset = offset + 20
        else:
            next_list = False

    return render_template('playlist.html', playlists=playlists)


@app.route('/organize')
def organize():
    if 'tokens' not in session:
        app.logger.error('No tokens in session.')
        abort(400)

    token = session.get('tokens').get('access_token')

    if 'playlist_id' in request.args:
        playlist_id = request.args.get('playlist_id')
    else:
        abort(500)

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
    }

    songs = {}

    offset = 0
    next_list = True

    while next_list:
        url = 'https://api.spotify.com/v1/playlists/' + playlist_id + '/tracks'

        params = (
            ('fields', 'items(track(id,name,album(name,artists(name)))),next'),
            ('offset', offset)
        )

        response = requests.get(url, headers=headers, params=params)

        for i in response.json()['items']:
            song = str(i['track']['name']) + " - " + str(i['track']['album']['artists'][0]['name']) + " (" + str(
                i['track']['album']['name']) + ")"
            song_id = "spotify:track:" + str(i['track']['id'])
            songs[song_id] = song
        if response.json()['next'] is not None:
            offset = offset + 100
        else:
            next_list = False

    return render_template('index.html', songs=songs)


@app.route('/send', methods=['GET', 'POST'])
def send():
    if 'tokens' not in session:
        app.logger.error('No tokens in session.')
        abort(400)

    token = session.get('tokens').get('access_token')

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
    }

    try:
        response = requests.get('https://api.spotify.com/v1/me', headers=headers)
        user_id = response.json()['id']

        url = 'https://api.spotify.com/v1/users/' + user_id + '/playlists'
        playlist_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))
        data = {
            'name': playlist_string,
            'public': 'false',
        }

        x = requests.post(url, headers=headers, data=json.dumps(data))

        playlist = x.json()['id']

        songs = request.json

        start_time = time.time()

        for i in songs:
            song_id = i.replace('songs_', '')
            playlist_url = 'https://api.spotify.com/v1/playlists/' + playlist + '/tracks?uris=' + song_id
            x = requests.post(playlist_url, headers=headers)
            print(song_id + " Status: " + str(x.status_code))
        print("--- Finished in %s seconds ---" % (time.time() - start_time))
    except:
        print("Error ...")
    return "Done"


if __name__ == '__main__':
    app.run(debug=True)
