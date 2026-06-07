# HomeOS

HomeOS is a personal desktop dashboard built with PyQt6. It brings a music player, net worth tracker, storage analyzer, OpenCode editor, RSS reader, system monitor, and ROM manager together in one place, wrapped in a consistent dark UI.

It is designed around the idea that your personal tools should live together instead of being scattered across browser tabs and terminal windows. Everything runs locally.

![Home screen](screenshots/homescreen.png)

## Modules

**Music Player** scans a local folder for audio files, plays them with a queue and shuffle, shows synced lyrics, and scrobbles to Last.fm if you connect an account.

![Music Player](screenshots/musicplayer.png)

**Net Worth Tracker** tracks your accounts, transactions, and sinking funds. You can enter everything manually inside the app, or if you use the LifeOS Android app, you can sync directly from a USB-connected phone over ADB.

![Net Worth Tracker](screenshots/networth.png)

**Storage Analyzer** shows disk usage for any folder on your machine. Add as many folders as you want and browse their contents. If you have network shares configured in `/etc/fstab`, those are detected automatically and you can mount them from inside the app.

![Storage Analyzer](screenshots/storageanalyzer.png)

**OpenCode Editor** is a GUI wrapper around [opencode](https://github.com/sst/opencode). It gives you a file tree, an editor, a terminal, a session log, and a git changes panel, all pointing at whatever project you have open. OpenCode must already be installed and on your PATH for this module to work.

![OpenCode Editor](screenshots/opencode.png)

**RSS Reader** lets you subscribe to any RSS or Atom feed and read articles without leaving the app. Feeds appear in a panel on the left, articles in the center, and the selected article opens in a reader pane on the right. You can load the full article text in place, or open it in a browser with one click. Unread counts are tracked per feed and clear automatically as you read.

![RSS Reader](screenshots/rssfeed.png)

**System Monitor** shows a live view of your system updated every two seconds. It covers CPU usage with a per-core breakdown, RAM and swap, GPU utilization and VRAM (NVIDIA cards via NVML), live network upload and download speeds, and a top processes table sorted by CPU.

![System Monitor](screenshots/systemmonitor.png)

**ROM Manager** is a visual frontend for your ROM collection. You configure each system by pointing it at a folder, selecting an emulator binary, and picking a platform for art lookups. The app scans your folders and fetches box art from TheGamesDB automatically. Double-click any game to launch it directly in the configured emulator. You can right-click any card to set custom art if the automatic result is wrong.

![ROM Manager](screenshots/rommanager.png)

## Requirements

### System dependencies

- Python 3.10 or newer
- `pip`
- `adb` (Android Debug Bridge) if you want the LifeOS sync feature in the Net Worth module. On Arch: `sudo pacman -S android-tools`. On Ubuntu/Debian: `sudo apt install adb`.
- `opencode` if you want the OpenCode Editor module. Install it with `npm install -g opencode` or follow the instructions at the [opencode repo](https://github.com/sst/opencode). After installing, confirm it works by running `opencode --version` in a terminal.
- An NVIDIA GPU and driver with NVML support if you want GPU stats in System Monitor. AMD and Intel GPUs are not currently shown.

### Python packages

```
PyQt6
PyQt6-WebEngine
psutil
mutagen
requests
pynvml
readability-lxml
```

## Installation

Clone the repository and install the dependencies:

```bash
git clone <your-repo-url> home_os
cd home_os
pip install PyQt6 PyQt6-WebEngine psutil mutagen requests pynvml readability-lxml
```

Then run it:

```bash
python main.py
```

That is it. No build step, no config file to create.

## Module setup

### Music Player

The player works immediately for local playback. To enable Last.fm scrobbling:

1. Go to [https://www.last.fm/api/account/create](https://www.last.fm/api/account/create) and create an API application. The name and description can be anything.
2. Copy your **API Key** and **Shared Secret**.
3. In HomeOS, open the Music Player and click **Account** in the menu bar, then **Connect Last.fm**.
4. If this is your first time, a dialog will ask for your API key and shared secret. Paste them in and click Save.
5. A browser window will open for you to authorize the app with your Last.fm account. After you approve it, come back to HomeOS and click the button to finish connecting.

Your credentials are saved locally in Qt settings and never leave your machine except to talk to the Last.fm API directly.

### Net Worth Tracker

On first launch, the module asks how you want to manage your data.

**Manual Entry** lets you create accounts, record transactions, and set up sinking funds directly in the app. Everything is saved to `~/.local/share/home_os/networth_manual.json`. Your net worth history is recorded automatically each time you save a change.

**LifeOS Backup** pulls financial data from the LifeOS Android app over ADB. For this to work:

1. Install the LifeOS app on your Android phone and make sure it is generating backups to `/storage/emulated/0/Backups/LifeOS/`.
2. Enable USB debugging on your phone (Settings > Developer Options > USB Debugging).
3. Connect your phone with a USB cable and accept the authorization prompt on the phone.
4. Confirm ADB can see the device by running `adb devices` in a terminal. You should see your device listed.
5. In HomeOS, open the Net Worth Tracker and click **Refresh**. It will pull the latest backup and parse it automatically.

You can switch between modes at any time with the **Change Source** button.

### Storage Analyzer

Click **+ Add Folder** to add any directory. The app will calculate its size in the background using `du` and show how much of the underlying drive it occupies. Large folders like `Downloads` or `node_modules` trees can take a few seconds to size up.

If you have NAS shares defined in `/etc/fstab` as `cifs` or `nfs` mounts, they appear automatically. You can mount them from inside the app if they are not already mounted (it will prompt for your sudo password, which is not stored anywhere).

### OpenCode Editor

Open the module and set your project folder using the file tree panel. OpenCode sessions are tracked and their output is shown in the Session Log tab. The module reads from `~/.config/opencode/` for your OpenCode configuration, and you can edit `AGENTS.md`, the context store, and `opencode.json` directly from the Preferences tab.

If `opencode` is not found on your PATH, the terminal panel will show an error when you try to start a session.

### Weather

The weather widget lives on the home screen above the module grid. Click **Set weather location** the first time, type a city name, and HomeOS will look up the coordinates and save them. After that, current conditions refresh automatically every 30 minutes. Click the gear icon at any time to change your location. Weather data comes from [Open-Meteo](https://open-meteo.com), which is free and requires no API key.

### RSS Reader

Click **+ Add Feed** and paste any RSS or Atom feed URL. Once added, click **Refresh All** to fetch articles. Feeds are stored locally and articles persist between sessions. The reader pane on the right shows the full content from the feed. For articles where the feed only provides a short summary, use **Load Full Article** to fetch and display the complete text in place, or **Open in Browser** to read it in your browser.

### System Monitor

The module works out of the box. Stats refresh every two seconds automatically.

GPU monitoring requires an NVIDIA card with the NVML library available. If your GPU is not NVIDIA, the GPU card will simply not appear. No configuration is needed.

### ROM Manager

1. Click **⚙ API Key** and paste your TheGamesDB API key. You can get a free key at [thegamesdb.net](https://thegamesdb.net). This is used only for box art lookups and the free tier includes 3000 requests per month. Art is cached locally after the first fetch.
2. Click **+ Add System** for each console you want to add. Fill in a name, point it at the folder containing your ROMs for that system, select the emulator binary, enter the file extensions your ROMs use (for example `.gba` or `.sfc .smc`), and pick the matching platform from the list for accurate art results.
3. Click **↻ Scan** to find all ROMs in your configured folders. Box art will start downloading in the background.
4. Double-click any game card to launch it directly in the configured emulator.

If you rename ROM files, click **↻ Scan** again. Old entries with missing files are removed automatically and the renamed files are picked up as new entries. If TheGamesDB returns wrong art for a game, right-click the card and choose **Change Art** to pick an image from your machine instead.

## Demo data

If you want to see the Net Worth Tracker with data before entering your own, run:

```bash
python gen_demo_data.py
```

This generates a set of obviously fake accounts and six months of history and sets the source to Manual mode. You can clear it by going into the tracker, deleting the accounts, and switching sources.

## Notes

- All data is stored locally. Nothing is sent to any server except Last.fm scrobbles (if you connect an account), Last.fm API calls for authentication, weather lookups via Open-Meteo, and TheGamesDB art lookups (if you configure an API key).
- The app saves its window geometry between sessions using Qt settings.
- The module menu in the menu bar changes depending on which module is active. The File menu always belongs to HomeOS itself.
