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
