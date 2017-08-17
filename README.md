# ss-tvirl
SmoothStreams script to supply TVirl with SmoothStreams support. EPG and playlist is retrieved via fog and altered/sent to TVirl. Hash token is automatically renewed when they expire.

## Credits

This script is based on the concept by notorious from the sstv forums/reddit. Alot of his work on his php scripts paved the way for this one, so huge thanks to him for doing near enough all the ground work on this concept. I've only made this because I didnt want to install an external webserver, e.g. apache/nginx.

Thanks to fog for his SmoothStreams.m3u8 and feed.xml supply, without this, it would not have been possible, atleast not so easily! So big props to him.

And ofcourse, thanks to SmoothStreams for such a great service.

## Requirements

All that is required is python 2.7 and the Flask pip module, you can install this by ```sudo python -m pip install -r requirements.txt```

Ofcourse TVirl and Live Channels for Android TV are also required, obviously.

This project may be compatible with QPython (if you can pip install flask), however that is untested, and not a requirement of mine.

## Setup

Ensure the script is executable: ```chmod a+x ss-tvirl.py``

Setup is pretty straight forward, set your username and password in the script (this is used to retrieve your hash token/renew it when it expires).
You must enter the site you are a member of, their values can be seen below:

```json
sites = {
    "Live247": "view247",
    "MyStreams/USport": "viewms",
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

You must then enter the IP and port you want the built in server to listen on, ```0.0.0.0``` will be accessible publicly, and ```127.0.0.1``` will be accessible to local only.

SERVER_HOST only needs to be changed if your listening on ```0.0.0.0```, this is a reachable location that TVirl will visit to start a stream, it will be redirected directly to SmoothStreams after the token has been checked/renewed.

SERVER_PATH can be used to specify a custom path for the playlist and epg file. This allows some sort of protection without requiring htaccess and all that jazz, just enter a suitably long/random path here.

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
sudo sytsemctl start sstv
sudo systemctl enable sstv
```

3. The script should now be running, you can verify this by ```tail -f status.log``` inside the same folder as the script.

## TVirl

Setting TVirl couldnt be any simpler, simply install TVirl, add a new channel from a playlist, when it asks for the playlist URL, it is simply ```http://SERVER_HOST:PORT/SERVER_PATH/playlist.m3u8```

When it asks for the EPG url, same as above its simply: ```http://SERVER_HOST:PORT/SERVER_PATH/epg.xml```

Once this is done and it has been scanned in successfully, you can enable the channel source in Live Channels settings menu and begin watching, hopefully!

## Demo

[![ss-tvirl demo](https://img.youtube.com/vi/Og9rjXB2C9w/0.jpg)](https://www.youtube.com/watch?v=Og9rjXB2C9w)
