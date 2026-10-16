# Soft Jazz Radio

Plays sets of 6 songs from a local MP3 library, then asks (by voice) what style you want next.

## Run

```bash
python3 server.py
```

- Player: http://localhost:8080 — click **Start** (browsers require a click before audio).
- Phone remote (same Wi-Fi): the URL printed in the terminal, ending in `/remote`.

## Add songs

Songs live in **collections** of **styles**: `music/<Collection>/<style>/`.

```
music/Jazz/jazz-noir/Some Song.mp3
music/Jazz/jazz-noir/style.jpeg      <- the picture on that style's button
music/Jazz/jazz-noir/style.txt       <- the prompt you used, if you like to keep it
music/Champagne_Ballroom/Easy_Foxtrot/...
```

- The style folder name is what you can say ("jazz noir"); underscores and hyphens become spaces.
  A style appears once it has at least one `.mp3`, `.m4a` or `.wav`; the filename becomes the song title.
- With two or more collections that have songs, the settings gear shows a **Collection** choice and the
  style buttons switch to that collection's styles. `Jazz` is offered first; change it with
  `MAIN_COLLECTION=Name python3 server.py`.
- A style folder placed directly in `music/` (no collection) also works.
- After adding or moving songs, run `python3 tracks.py` (it adds rows for new songs, and rows follow a style
  folder that moved, edits intact) and restart the server. Saved announcer clips follow a moved folder on their own.

**What the host says about a song.** Only what is known:
- *AI-made songs* (Mureka: an ffmpeg "Lavf" encoder tag plus an embedded cover) use the details in `tracks.csv` (instruments, mood, tempo from the style's prompt) and are never given an artist.
- *Real recordings* (an artist tag, and none of those Mureka marks) are introduced by what the file itself says: "Here's Tuxedo Junction, from Glenn Miller and His Orchestra", and now and then the album (skipped if it is long or a "disc" name). No instruments, moods, years or history are ever added.
- Anything else is introduced by its title alone.

## Announcer voices

List several in `.env` as `ELEVENLABS_VOICES=Name:voice_id, Name:voice_id` (find ids with
`python3 tts.py voices`). The first is the default. With two or more, a voice picker appears
on the start screen and in the controls; the choice is remembered in the browser and applies
from the next announcement.

## Casting to the TV

Chromecast can't hear you, so the mic stays on the device running the player.

- Mac: Chrome → ⋮ → Cast, Save and Share → Cast… → pick the TV. Choose to cast the *tab*
  and share audio. Speak to the Mac, or use the phone remote.
- Voice recognition needs Chrome (or Safari) and an internet connection; tap buttons always work.

## Mureka prompt idea

"Warm, velvety male baritone crooner, 1950s soft jazz, lush strings, brushed drums,
upright bass, gentle piano, slow tempo, romantic." Vary the style words per folder.

## The screen

The player is full-screen artwork with the controls out of the way. Move the mouse, press a
key, or use the phone remote and the controls and caption appear for a few seconds.

- **Station pictures:** put 1920x1080 JPG/PNG/WebP files in `images/` (any style) or in
  `images/<style>/` (only while that style plays; use the style's folder name, e.g. `images/jazz-noir/`). They rotate every 25 seconds, and the
  caption moves to the calmest corner of each picture. Reload the page after adding some.
- **Album covers:** each Mureka MP3 already contains its own cover. The current song's cover
  shows beside the caption. For the first few seconds of each song it fills the screen over
  a blurred copy of itself, then settles into the tile. A style with no pictures uses its
  songs' covers (blurred) as the background.
- **Timings** are constants at the top of `public/stage.js` (`IMAGE_SECONDS`,
  `CAPTION_SECONDS`, `FEATURE_SECONDS`; set `FEATURE_SECONDS = 0` to turn the big cover off).

## When the announcer can't speak

If ElevenLabs is unavailable (credits used up, no internet, a bad key), the music keeps playing
and the host falls back to a saved clip that is still true for the moment (a welcome, a "what's
next?", the right style's "coming right up", or that song's earlier introduction). If there is
none, that announcement is skipped, and a short note explains why, once. The technical detail
goes to the server's terminal, not the screen, and the app stops asking ElevenLabs for 30 minutes
after a credits or key problem (a few seconds after a network blip).

- `python3 fallback.py status` shows what is saved, by kind.
- `python3 fallback.py prepare` voices a few generic backup lines ("You've got it. Coming right
  up.") once, so a style with no saved clip still gets a reply. Run it when credits are available.
- `python3 tts.py usage` also shows your real ElevenLabs balance and reset date, if the key may see it.

## Radio mode

Settings (the gear) has a **play mode**: *Ask me what to play* (the default), *Shuffle all music*, or *Auto (by time of day)*, plus a **Quiet** switch that turns every spoken announcement off.

Shuffle, Auto and playlists work from one list: every song from every style in the pool (the whole library, the slot's styles, or the playlist's styles) is put in a list, shuffled, and played through; when it runs out it is shuffled again. Each song plays once per pass, so every style is heard, in proportion to how many songs it has. The two takes of one title count as one song (a random take plays each pass). Auto rebuilds the list when the time slot changes.

- **Auto** follows `schedule.json`: each slot lists the styles (`Jazz/cool-jazz`) or whole collections (`Jazz`) to play between `from` and `to` (24-hour clock; a slot may run past midnight). Hours outside every slot, or slots whose styles have no songs, play everything. Edit the file any time; it is read when the page starts.
- In the spoken modes the host also gives a time check soon after the top of each hour ("It's nine o'clock in the morning…") and a short station ID after 40 quiet minutes. There are only a few dozen of these lines, so they are voiced once and then replay for free.
- If nobody answers "what next?" twice in a row, the station stops asking and keeps playing the same style until someone picks something.
- The page resumes by itself after a reload (Chrome may insist on one click the first time), keeps trying if the server is down, retries after playback errors with a growing wait, and skips a song that freezes. For a kiosk that never needs a click, start Chrome with `--autoplay-policy=no-user-gesture-required`.
