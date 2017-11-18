#!/usr/bin/env python2.7
import logging
import os
import sys
import time
import zlib
from datetime import datetime, timedelta
from json import load, dump
from logging.handlers import RotatingFileHandler
from xml.etree import ElementTree as ET

import requests

try:
    from urlparse import urljoin
    import thread
except ImportError:
    from urllib.parse import urljoin
    import _thread

from flask import Flask, redirect, abort, request, Response

app = Flask(__name__)

token = {
    'hash': '',
    'expires': ''
}

playlist = ""
xmltv = ""

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
    payload = {
        "username": user,
        "password": passwd,
        "site": site
    }
    data = requests.get('http://auth.SmoothStreams.tv/hash_api.php', params=payload).json()
    if 'hash' not in data or 'valid' not in data:
        logger.error("There was no hash auth token returned from auth.SmoothStreams.tv...")
        exit(1)
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


def fetch_xmltv_gzip():
    global xmltv

    logger.info("Loading compressed epg from fog")
    # download gzip
    url = 'https://sstv.fog.pt/epg/xmltv5.xml.gz'
    resp = requests.get(url)
    # uncompress gzip
    data = zlib.decompress(resp.content, zlib.MAX_WBITS | 32)
    logger.info("Decompressed xmltv5.xml.gz")
    # store data in xmltv for epg requests
    xmltv = data
    return data


def build_channel_map():
    chan_map = {}
    resp = fetch_xmltv_gzip()
    xml = ET.fromstring(resp)
    pos = 0
    for channel in xml.iterfind('./channel'):
        pos += 1
        chan_map[pos] = channel.attrib['id']
    logger.debug("Built channel map with %d channels", len(chan_map))
    return chan_map


def build_playlist():
    # fetch smoothstreams feed json
    logger.debug("Loading feed from SmoothStreams")
    url = 'http://fast-guide.smoothstreams.tv/feed.json'
    feed = requests.get(url).json()
    # fetch chan_map
    chan_map = build_channel_map()
    # build playlist using the data we have
    new_playlist = "#EXTM3U\n"
    for pos in range(1, len(chan_map) + 1):
        # determine name
        if str(pos) in feed:
            channel_name = feed[str(pos)]['name'][5:].strip() if len(feed[str(pos)]['name'][5:]) > 1 else 'Unknown'
        else:
            logger.error("Channel %d had no feed information from %s", pos, url)
            continue
        # build channel url
        channel_url = urljoin(SERVER_HOST,
                              "%s/playlist.m3u8?channel=%d" % (SERVER_PATH, int(feed[str(pos)]['channel_id'])))
        # choose logo
        logo = feed[str(pos)]['img'] if feed[str(pos)]['img'].endswith('.png') else 'http://i.imgur.com/UyrGfW2.png'
        # build playlist entry
        try:
            new_playlist += '#EXTINF:-1 tvg-id="%s" tvg-name="%d" tvg-logo="%s" channel-id="%d",%s\n' % (
                chan_map[pos], int(feed[str(pos)]['channel_id']), logo, int(feed[str(pos)]['channel_id']),
                channel_name)
            new_playlist += '%s\n' % channel_url
        except:
            logger.exception("Exception while updating playlist: ")

    logger.info("Built playlist")
    return new_playlist


def thread_playlist():
    global playlist

    while True:
        time.sleep(86400)
        logger.info("Updating playlist...")
        try:
            tmp_playlist = build_playlist()
            playlist = tmp_playlist
            logger.info("Updated playlist!")
        except:
            logger.exception("Exception while updating playlist: ")


############################################################
# TVIRL <-> SSTV BRIDGE
############################################################

@app.route('/%s/<request_file>' % SERVER_PATH)
def bridge(request_file):
    global playlist, xmltv, token

    if request_file.lower().startswith('epg.'):
        logger.info("EPG was requested by %s", request.environ.get('REMOTE_ADDR'))
        return Response(xmltv, mimetype='application/xml')

    elif request_file.lower() == 'playlist.m3u8':
        if request.args.get('channel'):
            sanitized_channel = ("0%d" % int(request.args.get('channel'))) if int(
                request.args.get('channel')) < 10 else request.args.get('channel')
            logger.info("Channel %s playlist was requested by %s", sanitized_channel,
                        request.environ.get('REMOTE_ADDR'))
            check_token()
            ss_url = "http://%s.SmoothStreams.tv:9100/%s/ch%sq1.stream/playlist.m3u8?wmsAuthSign=%s==" % (
                SRVR, SITE, sanitized_channel, token['hash'])
            return redirect(ss_url, 302)

        else:
            logger.info("All channels playlist was requested by %s", request.environ.get('REMOTE_ADDR'))
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

    logger.info("Building initial playlist...")
    try:
        playlist = build_playlist()
    except:
        logger.exception("Exception while building initial playlist: ")
        exit(1)

    try:
        thread.start_new_thread(thread_playlist, ())
    except:
        _thread.start_new_thread(thread_playlist, ())

    logger.info("Listening on %s:%d at %s/", LISTEN_IP, LISTEN_PORT, urljoin(SERVER_HOST, SERVER_PATH))
    app.run(host=LISTEN_IP, port=LISTEN_PORT, threaded=True, debug=False)
    logger.info("Finished!")
