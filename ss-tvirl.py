#!/usr/bin/env python2.7
import logging
import os
import sys
from datetime import datetime, timedelta
from json import load, loads, dump
from logging.handlers import RotatingFileHandler
from urllib import urlencode, urlopen
from urlparse import urljoin

from flask import Flask, redirect, abort, request, Response

app = Flask(__name__)

token = {
    'hash': '',
    'expires': ''
}

############################################################
# CONFIG
############################################################

USER = ""
PASS = ""
SITE = "viewms"
SRVR = "deu"
LISTEN_IP = "127.0.0.1"
LISTEN_PORT = 6752
SERVER_HOST = "http://127.0.0.1:" + str(LISTEN_PORT)
SERVER_PATH = "sstv"

############################################################
# INIT
############################################################

# Setup logging
log_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)-10s - %(name)-10s -  %(funcName)-25s- %(message)s')

logger = logging.getLogger('ss-tvirl')
logger.setLevel(logging.DEBUG)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Console logging
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# Rotating Log Files
file_handler = RotatingFileHandler(os.path.join(os.path.dirname(sys.argv[0]), 'status.log'), maxBytes=1024 * 1024 * 2,
                                   backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

############################################################
# MISC
############################################################

TOKEN_PATH = os.path.join(os.path.dirname(sys.argv[0]), 'token.json')


def load_token():
    global token
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'r') as fp:
            token = load(fp)
            logger.debug("Loaded token %r, expires at %s", token['hash'], token['expires'])
    else:
        dump_token()


def dump_token():
    global token
    with open(TOKEN_PATH, 'w') as fp:
        dump(token, fp)
    logger.debug("Dumped token.json")


def array_flip(data):
    return {int(v): k for k, v in data.items()}


def find_between(s, first, last):
    try:
        start = s.index(first) + len(first)
        end = s.index(last, start)
        return s[start:end]
    except ValueError:
        return ""


############################################################
# SSTV
############################################################

def get_auth_token(user, passwd, site):
    url = "http://auth.SmoothStreams.tv/hash_api.php?" + urlencode({
        "username": user,
        "password": passwd,
        "site": site
    })
    resp = urlopen(url).read().decode("utf-8")
    data = loads(resp)
    if 'hash' not in data or 'valid' not in data:
        sys.exit("There was no hash auth token returned from auth.SmoothStreams.tv...")
    else:
        token['hash'] = data['hash']
        token['expires'] = (datetime.now() + timedelta(minutes=data['valid'])).strftime("%Y-%m-%d %H:%M:%S.%f")
        logger.info("Retrieved token %r, expires at %s", token['hash'], token['expires'])
        return


def check_token():
    # load and check/renew token
    if not token['hash'] or not token['expires']:
        # fetch fresh token
        logger.info("There was no token loaded, retrieving your first token...")
        get_auth_token(USER, PASS, SITE)
        dump_token()
    else:
        # check / renew token
        if datetime.now() > datetime.strptime(token['expires'], "%Y-%m-%d %H:%M:%S.%f"):
            # token is expired, renew
            logger.info("Token has expired, retrieving a new one...")
            get_auth_token(USER, PASS, SITE)
            dump_token()


def get_playlist():
    url = "http://sstv.fog.pt/utc/SmoothStreams.m3u8"
    resp = urlopen(url).read().decode('utf-8')
    logger.debug("Retrieved fogs SmoothStreams.m3u8")
    return remap_playlist(resp)


def remap_playlist(playlist):
    logger.debug("Remapping playlist from fog")
    # build id_map from chanlist.json by fog
    url = 'http://sstv.fog.pt/utc/chanlist.json'
    resp = loads(urlopen(url).read().decode("utf-8"))
    id_map = array_flip(resp)
    # build chan_map from existing playlist
    chan_map = {}
    for line in playlist.splitlines():
        if not line.startswith('#EXTINF'):
            continue
        # logger.debug("Line: %r", line)
        chan_name = find_between(line, 'tvg-name="', '"')
        chan_num = int(find_between(line, 'tvg-num="', '"'))
        chan_logo = find_between(line, 'tvg-logo="', '"').replace('https:https://', 'http://')
        chan_logo = chan_logo if chan_logo.endswith('.png') else 'http://i.imgur.com/UyrGfW2.png'
        chan_map[chan_num] = {
            'name': chan_name,
            'num': chan_num,
            'logo': chan_logo
        }
    # build playlist using the data we have
    new_playlist = "#EXTM3U\n"
    for pos in range(1, len(chan_map) + 1):
        channel_url = urljoin(SERVER_HOST, "%s/playlist.m3u8?channel=%d" % (SERVER_PATH, pos))
        new_playlist += '#EXTINF:-1 tvg-id="%s" tvg-name="%d" tvg-logo="%s" channel-id="%d",%s\n' % (
            id_map[pos], pos, chan_map[pos]['logo'], pos, chan_map[pos]['name'])
        new_playlist += '%s\n' % channel_url
    logger.info("Built remapped playlist")
    return new_playlist.strip()


############################################################
# TVIRL <-> SSTV BRIDGE
############################################################

@app.route('/%s/<request_file>' % SERVER_PATH)
def bridge(request_file):
    if request_file.lower().startswith('epg.'):
        logger.info("EPG was requested by %s", request.environ.get('REMOTE_ADDR'))
        return redirect('http://sstv.fog.pt/feed.xml', 302)

    elif request_file.lower() == 'playlist.m3u8':
        if request.args.get('channel'):
            sanitized_channel = ("0%d" % int(request.args.get('channel'))) if int(
                request.args.get('channel')) < 10 else request.args.get('channel')
            logger.info("Channel %s playlist was requested by %s", sanitized_channel,
                        request.environ.get('REMOTE_ADDR'))
            ss_url = "http://%s.SmoothStreams.tv:9100/%s/ch%sq1.stream/playlist.m3u8?wmsAuthSign=%s==" % (
                SRVR, SITE, sanitized_channel, token['hash'])
            check_token()
            return redirect(ss_url, 302)

        else:
            logger.info("All channels playlist was requested by %s", request.environ.get('REMOTE_ADDR'))
            playlist = get_playlist()
            logger.info("Sending playlist to %s", request.environ.get('REMOTE_ADDR'))
            return Response(playlist, mimetype='application/x-mpegURL')

    else:
        logger.info("Unknown requested %r by %s", request_file, request.environ.get('REMOTE_ADDR'))
        abort(404, "Unknown request")


############################################################
# MAIN
############################################################

if __name__ == "__main__":
    logger.info("Initializing")
    if os.path.exists('token.json'):
        load_token()
    check_token()
    logger.info("Listening on %s:%d at %s/", LISTEN_IP, LISTEN_PORT, urljoin(SERVER_HOST, SERVER_PATH))
    app.run(host=LISTEN_IP, port=LISTEN_PORT, threaded=True, debug=False)
    logger.info("Finished!")
