# Soft Jazz Radio

Plays sets of 6 songs from a local MP3 library, then asks (by voice) what style you want next.

## Run

```bash
python3 server.py
```

- Player: http://localhost:8080 — click **Start** (browsers require a click before audio).
- Phone remote (same Wi-Fi): the URL printed in the terminal, ending in `/remote`.

## Add songs

Each folder in `music/` is a style the app will offer. Folder name = what you say
(`music/bossa-nova/` → "bossa nova"). Drop `.mp3`, `.m4a` or `.wav` files in; the
filename becomes the song title. Add or rename folders any time and reload.

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
  `images/<style>/` (only while that style plays). They rotate every 25 seconds, and the
  caption moves to the calmest corner of each picture. Reload the page after adding some.
- **Album covers:** each Mureka MP3 already contains its own cover. The current song's cover
  shows beside the caption. For the first few seconds of each song it fills the screen over
  a blurred copy of itself, then settles into the tile. A style with no pictures uses its
  songs' covers (blurred) as the background.
- **Timings** are constants at the top of `public/stage.js` (`IMAGE_SECONDS`,
  `CAPTION_SECONDS`, `FEATURE_SECONDS`; set `FEATURE_SECONDS = 0` to turn the big cover off).
