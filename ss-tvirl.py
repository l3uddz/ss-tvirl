#!/usr/bin/env python2.7
import logging
import os
import shlex
import subprocess
import sys
import time
import zlib
from datetime import datetime, timedelta
from json import load, dump
from logging.handlers import RotatingFileHandler
from xml.etree import ElementTree as ET

import requests
from gevent.select import select
from gevent.wsgi import WSGIServer

try:
    from shlex import quote as cmd_quote
except ImportError:
    from pipes import quote as cmd_quote

try:
    from urlparse import urljoin
    import thread
except ImportError:
    from urllib.parse import urljoin
    import _thread

from flask import Flask, abort, request, Response, jsonify, render_template, redirect

app = Flask(__name__)

token = {
    'hash': '',
    'expires': ''
}

playlist = ""
xmltv = ""
plex_xmltv = ""
playlist_dict = {}

############################################################
# CONFIG
############################################################

USER = ""
PASS = ""
SITE = "viewstvn"
SRVR = "deu"
LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 6752
SERVER_HOST = "http://your-dynamic-dns.com:" + str(LISTEN_PORT)
TVIRL_SERVER_PATH = "sstv"
PLEX_SERVER_PATH = "plex"
PLEX_BUFFER_SIZE = 256
PLEX_FFMPEG_PATH = "/usr/bin/ffmpeg"

############################################################
# INIT
############################################################

# Setup logging
log_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)-10s - %(name)-10s -  %(funcName)-25s- %(message)s')

logger = logging.getLogger('ss-tvirl-plexdvr')
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
# SSTV / PLEX
############################################################

def get_auth_token(user, passwd, site):
    payload = {
        "username": user,
        "password": passwd,
        "site": site
    }
    data = requests.get(
        'http://auth.SmoothStreams.tv/hash_api.php' if 'mma' not in site else 'https://www.mma-tv.net/loginForm.php',
        params=payload).json()
    if 'hash' not in data or 'valid' not in data:
        logger.error("There was no hash auth token returned from auth.SmoothStreams.tv: %s", data)
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
    global xmltv, plex_xmltv

    logger.info("Loading compressed epg from SmoothStreams")
    # download gzip
    url = 'https://guide.smoothstreams.tv/altepg/xmltv5.xml.gz'
    resp = requests.get(url)
    # uncompress gzip
    data = zlib.decompress(resp.content, zlib.MAX_WBITS | 32)
    logger.info("Decompressed xmltv5.xml.gz")
    # store data in xmltv for epg requests
    xmltv = data
    plex_xmltv = fog_to_plex_epg(data)
    return data


def fog_to_plex_epg(epg_data):
    tree = ET.fromstring(epg_data)
    chan_map = {}
    pos = 0

    logger.info("Processing fog epg to plex epg")

    # change channel ids and build chan_map
    for a in tree.iterfind('channel'):
        pos += 1
        chan_map[a.attrib['id']] = str(pos)
        a.attrib['id'] = str(pos)

    # loop programmes
    for a in tree.iterfind('programme'):
        # change channel
        a.attrib['channel'] = chan_map[a.attrib['channel']]

    logger.info("Built plex epg")
    return ET.tostring(tree)


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
    global playlist_dict
    tmp_playlist_dict = {}

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
                              "%s/playlist.m3u8?channel=%d" % (TVIRL_SERVER_PATH, int(feed[str(pos)]['channel_id'])))
        # choose logo
        logo = feed[str(pos)]['img'] if feed[str(pos)]['img'].endswith('.png') else 'http://i.imgur.com/UyrGfW2.png'
        # build playlist entry
        try:
            new_playlist += '#EXTINF:-1 tvg-id="%s" tvg-name="%d" tvg-logo="%s" channel-id="%d",%s\n' % (
                chan_map[pos], int(feed[str(pos)]['channel_id']), logo, int(feed[str(pos)]['channel_id']),
                channel_name)
            new_playlist += '%s\n' % channel_url
            # add channel to tmp_playlist_dict
            tmp_playlist_dict[int(feed[str(pos)]['channel_id'])] = {
                'channel_name': channel_name,
                'channel_number': int(feed[str(pos)]['channel_id']),
                'channel_id': chan_map[pos],
                'channel_url': channel_url
            }
        except:
            logger.exception("Exception while updating playlist: ")

    playlist_dict = tmp_playlist_dict
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


def ffmpeg_pipe_stream(stream_url):
    global PLEX_FFMPEG_PATH, PLEX_BUFFER_SIZE

    pipe_cmd = "%s -re -i %s " \
               "-codec copy " \
               "-nostats " \
               "-loglevel 0 " \
               "-bsf:v h264_mp4toannexb " \
               "-f mpegts " \
               "-tune zerolatency " \
               "pipe:1" % (PLEX_FFMPEG_PATH, cmd_quote(stream_url))

    p = subprocess.Popen(shlex.split(pipe_cmd), stdout=subprocess.PIPE, bufsize=-1)
    try:
        pipes = [p.stdout]
        while pipes:
            ready, _, _ = select(pipes, [], [])
            for pipe in ready:
                data = pipe.read(PLEX_BUFFER_SIZE << 10)
                if data:
                    yield data
                else:
                    pipes.remove(pipe)
    except Exception:
        pass
    except GeneratorExit:
        pass

    try:
        p.terminate()
    except Exception:
        pass
    return


############################################################
# HDHOMERUN <-> PLEX DVR <-> SSTV BRIDGE
############################################################

discoverData = {
    'FriendlyName': 'ss-tvirl-plexdvr',
    'Manufacturer': 'Silicondust',
    'ModelNumber': 'HDTC-2US',
    'FirmwareName': 'hdhomeruntc_atsc',
    'TunerCount': 6,
    'FirmwareVersion': '20150826',
    'DeviceID': '12345678',
    'DeviceAuth': 'test1234',
    'BaseURL': '%s' % SERVER_HOST,
    'LineupURL': '%s/lineup.json' % SERVER_HOST
}


@app.route('/%s/<request_file>' % PLEX_SERVER_PATH)
def plex_bridge(request_file):
    global plex_xmltv, playlist_dict
    lineup = []

    if request_file.lower().startswith('epg.'):
        # EPG request here
        logger.info("Plex EPG was requested by %s", request.environ.get('REMOTE_ADDR'))
        return Response(plex_xmltv, mimetype='application/xml')
    elif request_file.lower() == 'playlist.m3u8' and request.args.get('channel'):
        # Plex requested a channel, lets return the transcoded stream
        channel = request.args.get('channel')
        channel = channel[:channel.index("?")] if '?' in channel else channel
        sanitized_channel = ("0%d" % int(channel)) if int(channel) < 10 else channel
        logger.info("Channel %s was requested from Plex by %s", sanitized_channel,
                    request.environ.get('REMOTE_ADDR'))

        check_token()
        rtmp_url = "rtmp://%s.SmoothStreams.tv:3625/%s?wmsAuthSign=%s/ch%sq1.stream" % (
            SRVR, SITE, token['hash'], sanitized_channel)
        return Response(ffmpeg_pipe_stream(rtmp_url), mimetype='video/mpeg2')
    elif request_file.lower().startswith('discover.json'):
        # discover.json request here
        return jsonify(discoverData)
    elif request_file.lower().startswith('lineup_status.json'):
        # lineup_status.json request here
        return jsonify({
            'ScanInProgress': 0,
            'ScanPossible': 1,
            'Source': "Cable",
            'SourceList': ['Cable']
        })
    elif request_file.lower().startswith('lineup.json'):
        # lineup.json request here
        for channel_number, channel_data in playlist_dict.items():
            lineup.append({'GuideNumber': str(channel_number),
                           'GuideName': channel_data['channel_name'],
                           'URL': channel_data['channel_url'].replace(TVIRL_SERVER_PATH, PLEX_SERVER_PATH)
                           })

        return jsonify(lineup)
    elif request_file.lower().startswith('lineup.post'):
        # lineup.post request here
        return ''
    elif request_file.lower().startswith('device.xml'):
        # device.xml request here
        return render_template('device.xml', data=discoverData), {'Content-Type': 'application/xml'}
    else:
        logger.info("Unknown requested %r by %s", request_file, request.environ.get('REMOTE_ADDR'))
        return abort(404, "Unknown request")


############################################################
# TVIRL <-> SSTV BRIDGE
############################################################

@app.route('/%s/<request_file>' % TVIRL_SERVER_PATH)
def tvirl_bridge(request_file):
    global playlist, xmltv, token

    if request_file.lower().startswith('epg.'):
        # EPG request here
        logger.info("TvIRL EPG was requested by %s", request.environ.get('REMOTE_ADDR'))
        return Response(xmltv, mimetype='application/xml')

    elif request_file.lower() == 'playlist.m3u8':
        if request.args.get('channel'):
            # tvIRL Requested this channel, let's redirect them directly to SmoothStreams
            channel = request.args.get('channel')
            channel = channel[:channel.index("?")] if '?' in channel else channel
            sanitized_channel = ("0%d" % int(channel)) if int(channel) < 10 else channel
            logger.info("Channel %s was requested from TvIRL by %s", sanitized_channel,
                        request.environ.get('REMOTE_ADDR'))

            check_token()
            ss_url = "http://%s.SmoothStreams.tv:9100/%s/ch%sq1.stream/playlist.m3u8?wmsAuthSign=%s" % (
                SRVR, SITE, sanitized_channel, token['hash'])
            return redirect(ss_url, 302)

        else:
            # tvIRL Requested the playlist of all available channels, lets return it too them
            logger.info("All channels playlist was requested from TvIRL by %s", request.environ.get('REMOTE_ADDR'))
            return Response(playlist, mimetype='application/x-mpegURL')

    else:
        logger.info("Unknown requested %r by %s", request_file, request.environ.get('REMOTE_ADDR'))
        return abort(404, "Unknown request")


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

    logger.info("Listening on %s:%d at %s/ for Live Channels + tvIRL", LISTEN_IP, LISTEN_PORT,
                urljoin(SERVER_HOST, TVIRL_SERVER_PATH))
    logger.info("Listening on %s:%d at %s/ for Plex DVR", LISTEN_IP, LISTEN_PORT,
                urljoin(SERVER_HOST, PLEX_SERVER_PATH))

    server = WSGIServer((LISTEN_IP, LISTEN_PORT), app, log=None)
    server.serve_forever()
    logger.info("Finished!")
