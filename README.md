# ss-tvirl
SmoothStreams script to supply TvIRL with SmoothStreams support. EPG and playlist is retrieved via fog and altered/sent to TVirl. Hash token is automatically renewed when they expire.

It also has the added capability of feeding streams to Plex DVR!

## Credits

This script is based on the concept by notorious from the sstv forums/reddit. Alot of his work on his php scripts paved the way for this one, so huge thanks to him for doing near enough all the ground work on this concept. I've only made this because I didnt want to install an external webserver, e.g. apache/nginx.

Thanks to fog for his SmoothStreams.m3u8 and feed.xml supply, without this, it would not have been possible, atleast not so easily! So big props to him.

And ofcourse, thanks to SmoothStreams for such a great service.

## Requirements

All that is required is python 2.7 and the Flask pip module, you can install this by ```sudo python -m pip install -r requirements.txt```

Ofcourse TvIRL and Live Channels for Android TV are also required.

Plex DVR requires ffmpeg, you can install this by ```sudo apt install ffmpeg```

This project may be compatible with QPython (if you can pip install flask / gevent), however that is untested, and not a requirement of mine.

## Setup

Ensure the script is executable: ```chmod a+x ss-tvirl.py```

Setup is pretty straight forward, set your username and password in the script (this is used to retrieve your hash token/renew it when it expires).
You must enter the site you are a member of, their values can be seen below:

```json
sites = {
    "Live247": "view247",
    "StarStreams": "viewss",
    "MMA/SR+": "viewmmasr",
    "StreamTVnow": "viewstvn",
    "MMA-TV/MyShout": "mmatv",
}
```

You must enter the server you wish to use, their values can be seen below:

```json
servers = {
    "EU Random": "deu",
    "DE-Frankfurt": "deu.de1",
    "NL": "deu.nl",
    "NL-1": "deu.nl1",
    "NL-2": "deu.nl2",
    "NL-3": "deu.nl3",
    "UK-London": "deu.uk",
    "UK-London1": "deu.uk1",
    "UK-London2": "deu.uk2",
    "US Random": "dna",
    "US-East": "dnae",
    "US-East-NJ": "dnae1",
    "US-East-VA": "dnae2",
    "US-East-MTL": "dnae3",
    "US-East-TOR": "dnae4",
    "US-West": "dnaw",
    "US-West-PHX": "dnaw1",
    "US-West-SJ": "dnaw2",
    "Asia": "dap",
}
```

You must then enter the IP and port you want the built in server to listen on, ```0.0.0.0``` will be accessible publicly, and ```127.0.0.1``` will be accessible to local only. If you are on a network, specify your network IP so other devices on the network can also access it.

SERVER_HOST only needs to be changed if your listening on ```0.0.0.0```, this is a reachable location that tvIRL / Plex DVR will visit to start a stream. TvIRL will be redirected directly to SmoothStreams after the token has been checked/renewed and Plex DVR will proxy the stream via ffmpeg.

TVIRL_SERVER_PATH + PLEX_SERVER_PATH can be used to specify a custom path for the playlist and epg files. This allows some sort of protection without requiring htaccess and all that jazz, just enter a suitably long/random path here.

PLEX_BUFFER_SIZE is how many KB to read from ffmpeg before sending to the client. The default should be fine, however this may need some fine-tuning by yourself until you are happy. 256 - 512 seems to be pretty safe bets.

PLEX_FFMPEG_PATH is the path to the ffmpeg binary, the default should be fine, however double check with ``which ffmpeg``.

## Running

Running the script is as easy as:
```./ss-tvirl.py```

If you want it to be automatically started on boot, you can use the included systemd service file, e.g.:

1. Set the user you wish to execute the script
```nano system/sstv.service``` - change the USER and GROUP variable to your user, you wish to run the script. Also change the location of the script in ExecStart, it might be different for you than the default one set. Set the WorkingDirectory to the directory of the script.

2. Copy the service file, reload systemctl and start/enable it for boot
```
sudo cp system/sstv.service /etc/systemd/system
sudo systemctl daemon-reload 
sudo systemctl start sstv
sudo systemctl enable sstv
```

3. The script should now be running, you can verify this by ```tail -f status.log``` inside the same folder as the script.

## TVirl

Setting TVirl couldnt be any simpler, simply install TVirl, add a new channel from a playlist, when it asks for the playlist URL, it is simply ```http://SERVER_HOST:PORT/SERVER_PATH/playlist.m3u8```

When it asks for the EPG url, same as above its simply: ```http://SERVER_HOST:PORT/SERVER_PATH/epg.xml```

Once this is done and it has been scanned in successfully, you can enable the channel source in Live Channels settings menu and begin watching, hopefully!

## Plex DVR

Setting Plex DVR up is very straightforward as-well. Simply go to the Live TV section in the settings menu of your Plex Server.

Click the ``Don't see your device?`` where you will be asked to enter the device address, this will be ``SERVER_HOST:PORT/PLEX_SERVER_PATH`` (e.g. ``your-dynamic-dns.com:6752/plex``). After pressing continue, you should be presented with the channel list, press continue. 

You should now be asked to enter a post code/zip code, above that is some yellow text, press this text where you will be-able to provide an XMLTV location. This location will be ``http://SERVER_HOST:PORT/SERVER_PATH/epg.xml`` (e.g. ``http://your-dynamic-address.com:6752/plex/epg.xml``). Press continue and it should load the EPG, press continue again. 

Now you must wait for Plex to finish the setup process. Upon completion you should now have SmoothStreams access directly from within Plex.

## Demo

[![ss-tvirl demo](https://img.youtube.com/vi/Og9rjXB2C9w/0.jpg)](https://www.youtube.com/watch?v=Og9rjXB2C9w)
