# Loadout Recorder: setting up the gaming PC

The Loadout Recorder saves short clips of your Steam games without you pressing anything.
Nothing records continuously any more. When a Steam game starts, OBS keeps the
last 60 seconds of play in memory (its **replay buffer**), and:

- every minute the recorder saves those 60 seconds as a clip (an **automatic** clip);
- whenever you see something great, press **F9** (the OBS **Save Replay** key) and
  the last 60 seconds are saved too (your **pick**).

Each clip is sent within seconds, while you keep playing, as
`<steam id>_<game name>_<date>_auto.mp4` or `..._pick.mp4` in the
`Loadout Recorder` folder inside your user folder (`C:\Users\<you>\Loadout Recorder`).
A clip is about 100-170 MB. The folder is kept out of Videos on purpose: OneDrive
often backs up Videos, and gameplay would fill its free space. Syncthing copies
each clip to the Loadout Daily PC, where the app always turns your picks into
Shorts and keeps only the best automatic clips.

Everything here is free. Setup takes about 20 minutes, once.

## 1. Install OBS Studio

1. Download OBS Studio from https://obsproject.com and install it in the default folder.
2. Open OBS. If the auto-configuration wizard appears, choose **Optimize just for recording**.

## 2. Set up OBS (once)

**Record only the game's sound.** Your microphone, Discord and music stay out of the video.

1. **Settings > Audio**: set **Desktop Audio** and **Mic/Auxiliary Audio** to **Disabled**.
2. In **Sources** (bottom of the window), press **+ > Game Capture**, name it `Game`, then:
   - **Mode**: Capture any fullscreen application
   - tick **Capture Audio (BETA)**

**Video quality**

3. **Settings > Video**: Base and Output resolution **1920x1080**, FPS **60**.
4. **Settings > Output**: Output Mode **Advanced**, then the **Recording** tab:
   - Recording Format: **MP4**
   - Video Encoder: **NVIDIA NVENC H.264**
   - Rate Control: **CQP**, CQ Level **23**

   Your NVIDIA card does the work, so games lose almost no speed.
   You don't need to choose a Recording Path: the recorder sets it.

**Clips instead of recordings**

5. **Settings > Output > Replay Buffer**: tick **Enable Replay Buffer** and set
   **Maximum Replay Time** to **60** seconds. If a **Maximum Memory** box is shown,
   leave it at 512 MB or more. Press **Apply**.
6. **Settings > Hotkeys**: find **Save Replay**, click the box next to it and press
   a key you don't use in games (**F9** is a good choice). Press **OK**.

**Let the recorder talk to OBS**

7. **Tools > WebSocket Server Settings**: tick **Enable WebSocket server** and
   **Enable Authentication**, press **Show Connect Info** and copy the **Server Password**.
   Press **OK**.

You can close OBS now. The recorder opens it by itself when a game starts.

## 3. Install the recorder

1. On GitHub, open the Loadout Daily repository, press **Code > Download ZIP**,
   and extract it anywhere (Downloads is fine).
2. Open the extracted folder, then the `recorder` folder.
3. Click the address bar of the folder window, type `powershell` and press Enter.
4. In the blue window, type this and press Enter:

   ```
   powershell -ExecutionPolicy Bypass -File .\install-recorder.ps1
   ```

5. Paste the OBS password (right-click pastes; nothing shows while you type) and press Enter.

You should see **Loadout Recorder is installed and running**. It starts with Windows from now on.
To update it later, download the new ZIP and run the same command again.

## 4. Test it

1. Start any Steam game and play for two minutes. Press **F9** once along the way.
2. Open `C:\Users\<you>\Loadout Recorder` (you can leave the game running). Files like
   `1492070_Crimson-Desert_2026-11-10_21-05-33_auto.mp4` and one ending in `_pick.mp4`
   should be there.
3. Close the game.

Nothing there? Open `%APPDATA%\LoadoutRecorder\recorder.log` (paste that into the
folder address bar). The last lines say what went wrong, for example
"wrong WebSocket password" (run the installer again to type the password again) or
"OBS has the replay buffer turned off" (do step 5 of part 2 again).

## 5. Send the clips to the Loadout Daily PC (Syncthing)

Do this on **both** PCs.

1. Download Syncthing for Windows from https://syncthing.net/downloads
   (the **Syncthing Windows Setup**), install it with the default options, and
   let it start with Windows. Its page opens in the browser at http://127.0.0.1:8384.
2. On the **Loadout Daily PC**: press **Actions > Show ID** and copy the ID.
3. On the **gaming PC**: press **Add Remote Device**, paste the ID, name it `Loadout Daily`, and save.
4. On the **Loadout Daily PC**: accept the new device when Syncthing asks.
5. On the **gaming PC**: press **Add Folder**:
   - Folder Label: `Loadout Recorder`
   - Folder Path: `C:\Users\<you>\Loadout Recorder`
   - **Sharing** tab: tick `Loadout Daily`
   - Save.
6. On the **Loadout Daily PC**: accept the folder, set its path to
   `C:\Users\Webcomum\Loadout Inbox`, and leave the folder type as **Send & Receive**.

From now on every clip copies itself over your home network a few seconds after
it is saved. When the app has made a Short from a clip (or decided not to use it),
it deletes it, and Syncthing deletes it on the gaming PC too, so neither disk fills up.

## Good to know

- Only games started from **Steam** are clipped. Other launchers are ignored.
- While a Steam game runs, the recorder is in charge of OBS: if OBS or the
  replay buffer stops (a crash, or you pressed Stop Replay Buffer), it starts them
  again, and it turns the replay buffer off when the game closes. Your own OBS
  recordings outside games go to `%LOCALAPPDATA%\LoadoutRecorder\recording` and are left alone.
- If the PC crashes mid-game, the clips already saved are still sent; only the
  last minute or less is lost.
- To pause the recorder, press Win+R, type `shell:startup`, delete
  **Loadout Recorder**, and restart the PC. Run the installer again to bring it back.
