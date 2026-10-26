# Loadout Recorder: setting up the gaming PC

The Loadout Recorder records your Steam games without you pressing anything.
When a Steam game starts, OBS starts recording. When you close the game, the
recording is saved as `<steam id>_<game name>_<date>.mp4` in
the `Loadout Recorder` folder inside your user folder (`C:\Users\<you>\Loadout Recorder`).
It is kept out of Videos on purpose: OneDrive often backs up Videos, and gameplay
would fill its free space. Syncthing then copies it to the Loadout Daily PC,
where the app picks the best moments for a First look video.

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
   - Recording Format: **Hybrid MP4** (or MP4 if Hybrid is not listed)
   - Video Encoder: **NVIDIA NVENC H.264**
   - Rate Control: **CQP**, CQ Level **23**

   Your NVIDIA card does the recording, so games lose almost no speed.
   An hour of play is about 10 GB. You don't need to choose a Recording Path:
   the recorder sets it.

**Let the recorder talk to OBS**

5. **Tools > WebSocket Server Settings**: tick **Enable WebSocket server** and
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

1. Start any Steam game, play one minute, then close the game.
2. Open `C:\Users\<you>\Loadout Recorder`. A file like `1492070_Sker-Ritual_2026-10-26_21-05-33.mp4` should be there.

Nothing there? Open `%APPDATA%\LoadoutRecorder\recorder.log` (paste that into the
folder address bar). The last lines say what went wrong, for example
"wrong WebSocket password". Run the installer again to type the password again.

## 5. Send the recordings to the Loadout Daily PC (Syncthing)

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

From now on every recording copies itself over your home network. When the app
has made a video from a recording, it deletes it, and Syncthing deletes it on the
gaming PC too, so neither disk fills up.

## Good to know

- Only games started from **Steam** are recorded. Other launchers are ignored.
- While a Steam game runs, the recorder is in charge of OBS: if OBS or the
  recording stops (a crash, or you pressed Stop), it starts them again, and it
  stops the recording when the game closes. Your own OBS recordings outside
  games go to `%LOCALAPPDATA%\LoadoutRecorder\recording` and are left alone.
- If the PC crashes mid-game, the part already recorded is still saved.
- To pause the recorder, press Win+R, type `shell:startup`, delete
  **Loadout Recorder**, and restart the PC. Run the installer again to bring it back.
