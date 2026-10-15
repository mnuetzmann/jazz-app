# Soft Jazz Radio

Plays sets of 6 songs from a local MP3 library, then asks (by voice) what style you want next.

## Run

```bash
python3 server.py
```

- Player: http://localhost:3000 — click **Start** (browsers require a click before audio).
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
