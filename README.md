## Download Tori Download Manager v0.22

[⬇ Download Windows Installer](https://github.com/robijoychakma375-hash/ToriDownload/releases/download/v0.22.0/ToriDownload-Setup-v0.22.exe)

[⬇ Download Portable ZIP](https://github.com/robijoychakma375-hash/ToriDownload/releases/download/v0.22.0/ToriDownload-Portable-v0.22.zip)

# Tori Download v0.22 (Windows testing build)

> **Latest source version:** v0.22.0. The source repository does not contain a compiled Windows EXE. Build it on Windows using `build-windows.bat`, or download the installer and portable ZIP from a published GitHub Release when available.

## Quick start

On Windows 11, install Python 3.11+ and Inno Setup 6. Clone or download this repository, then run `build-windows.bat` from the project folder. The finished installer and portable ZIP appear in `release-dist`. Install/run one version, then open `chrome://extensions` or `edge://extensions`, enable Developer mode, choose **Load unpacked**, and select that version's `extension` directory. The browser extension is not published in a store and must be added manually.

Only save files and media you have permission to download. The video feature does not bypass DRM or access restrictions. See the full instructions and limits below before distributing a release.

A personal Windows download manager with a desktop queue and an Edge/Chrome extension. This is still a testing build, not a production-ready IDM replacement. It supports direct HTTP(S) files and supported public video pages. The app applies no artificial bandwidth cap; actual speed depends on the server, network and disk.

## What's new

- A refreshed desktop dashboard adds active, completed and attention counts; the queue uses taller, readable rows with a status progress bar. Empty categories display a clear message, and the empty All Downloads view has an Add URL action. Confirmation dialogs show the file name and destination more clearly. The browser popup follows the same dark palette and uses switch indicators, while the video overlay shows a label on hover. This release changes presentation only; download speeds and capture behavior have not changed.


- The Tori video confirmation now loads available resolutions from the video source and offers **Auto**, advertised sizes such as **480p / 1080p / 1440p**, and **MP3** if audio is present. Selecting MP3 changes the proposed filename to `.mp3` and uses FFmpeg to convert the downloaded audio; other choices keep the selected resolution as an upper limit. The choice is stored with the queue job and reused on retry. If format discovery fails, Auto remains available; discovery never guarantees a particular resolution will actually download.

- The extension adds a small Tori button at the corner of a visible HTML5 video (including player pages on YouTube/Facebook when a video element is visible). Clicking it sends the playable media URL or page URL to a Tori confirmation, with a suggested filename and folder; no URL copy is needed. Tori uses yt-dlp and a bundled FFmpeg binary to try public, supported streams; a video job appears in the same queue and shows progress. Stop/Resume retry using yt-dlp's partial files when supported. Login-only, protected/DRM, live or site-changed streams may fail; YouTube/Facebook success is not guaranteed. Only download videos you are permitted to save.

- One Windows build creates **two releases**: `release-dist/ToriDownload-Setup-v0.22.exe` (installer) and `release-dist/ToriDownload-Portable-v0.22.zip` (portable single-file EXE plus extension). The portable ZIP includes a marker so Tori saves its queue, settings, and default downloads under its extracted folder. The portable copy starts at sign-in only if you turn that on in Settings; installed Tori starts at sign-in by default. You cannot run both copies together because they share one local connector port.

- On Windows, installed Tori starts at user sign-in and stays in the system tray. Press the window X to keep the connector and active downloads running in the background; use the tray icon's **Open Tori** to restore it. **Quit Tori** from the tray or toolbar exits the app. Download offers bring the window forward for confirmation. Settings has a **Start Tori when I sign in to Windows** switch; the installed default is ON and the portable default is OFF. A second launch reports that Tori is already running rather than altering the active queue.

- A dark navy download-manager window based on the supplied reference: readable 34-pixel table rows, narrower category sidebar, subtle grid lines, matching vector line icons, colored status text and a progress bar in the status column. Row separators remain visible across alternating row backgrounds. Click any table column heading to change sorting. Last Try shows the date and time when Tori last attempted the file; older entries first display a dash until retried.
- **Settings** opens a dialog to change or open the default folder for downloads received from the extension and future manual downloads. Its path appears along the bottom of the window and persists across restarts. Selecting a file displays its folder along the bottom. Older jobs keep their original folder.
- **New URL** asks for a filename and an individual save folder. **Resume** starts or retries the selected job, **Stop** pauses it, and **Delete** confirms removal from the list and removes unfinished partial bytes. Finished files stay on disk. **Quit** asks before exiting if downloads are active. The window X hides Tori in the tray. Right-click a job to **Open folder** or **Rename** a paused or finished job's disk filename and list entry. **Browsers** shows connection information, opens the unpacked extension folder and lets you copy its path. **About** identifies the build. Buttons give an explanation at the bottom when there is no applicable selection.
- Browser auto capture waits briefly for Chrome/Edge to provide the actual filename; the desktop app also checks the server's Content-Disposition header when available. Files now save with their readable filename rather than a numeric prefix. If a filename is already taken, the app adds `(2)`, `(3)`, etc. Older saved files retain their existing prefix and location so upgrades do not break partial downloads.
- With Auto capture ON, direct file clicks are held for confirmation before Chrome creates a download item. **Tori only** is also ON by default: Chrome fallback is disabled; when the app is closed, a direct click shows a warning and does not download. A separate button in the extension popup can turn Tori only OFF to restore browser fallback.
- Automatic capture starts **ON** on a fresh extension install, and a manual OFF selection stays saved on browser restarts. The Bandwidth and total-speed labels average short bursts and fade during a stalled read. This makes the display easier to read; it does not change actual server or network transfer speed and does not impose a rate limit.
- Extension captures open a **Confirm download** dialog in Tori to choose the filename and folder. With Tori only ON, script and address-bar downloads are canceled as soon as Chrome reports their creation, before Tori offers the URL. Chrome may still briefly transfer data or display an entry because its event arrives *after* the download begins. If the browser file already completed, its entry stays visible and Tori does not offer a duplicate. Turn Tori only OFF for the older pause-and-browser-fallback behavior.
- Canceling a file and then clicking the same link creates a fresh confirmation request. The extension clears any browser-fallback marker from an earlier attempt on each new direct click, and content scripts poll the app through short status messages instead of holding one long message channel open. When Tori only is ON and the server rejects a file, it stays stopped; turn Tori only OFF if you need browser fallback.

Some file servers provide only a random URL ID and no usable filename header; in that case the extension might not have a meaningful name to send. Edit the suggested filename in the confirmation dialog, or right-click the job and use **Rename** after pausing or finishing the download. The dialog proposes the default folder selected in Settings. The appearance follows the reference's layout and palette but uses a custom Tkinter canvas; it does not bundle or copy the referenced app's assets.

## Build the two Windows releases

On a Windows 11 computer, install **Python 3.11 or newer** with Add Python to PATH and **Inno Setup 6**. Extract the project ZIP to a writable folder and double-click `build-windows.bat`. Leave the window open until it says both files are ready. Find `ToriDownload-Setup-v0.22.exe` and `ToriDownload-Portable-v0.22.zip` together in `release-dist`. The builder uses PyInstaller one-file mode and bundles the video engine and FFmpeg, so outputs are larger than before. No Python is needed on PCs where either finished release is used. If Inno Setup is missing, the portable ZIP is built and the script explains how to finish the installer; the installer is not produced.

**Installable:** Run the setup EXE, then launch Tori once. It stores its queue under `%LOCALAPPDATA%\FrejaDownloadManager` for compatibility with existing data, registers sign-in startup by default, and includes the browser extension folder.

**Portable:** Extract the entire portable ZIP to a writable folder and run `ToriDownload.exe`. Keep `extension` and `portable.flag` beside it. `ToriData` and `Downloads` appear in that folder after first launch. This mode does not install the app; Windows sign-in startup is initially OFF, but you can enable it in Settings. If enabled, move the portable folder only after turning startup OFF or launch Tori again to refresh its path. Saved job paths are absolute, so finish or remove existing jobs before moving the folder. The browser extension still needs to be loaded once.

## Try it on Windows 11

1. Install Python 3.11 or newer, with **Add Python to PATH** enabled.
2. For source testing, extract this project ZIP into a permanent folder. Run `py -3 -m pip install -r requirements.txt`, then `py -3 app.py` there. For regular use, build and run one of the two finished releases above.
3. Remove the old unpacked Tori extension in `edge://extensions` or `chrome://extensions`. Enable Developer mode, choose **Load unpacked**, and select the running version's `extension` folder (installed under its app folder or beside the portable EXE). The pre-click feature runs on HTTP(S) pages, so the browser may ask for permission to read and change data on websites. The script reads direct link URLs when Auto capture is ON; the video button sends the selected video/page URL only when clicked. Without page access Chrome's later download event is the only available handoff.
4. Open the extension popup: the green **ON** badge means the app is connected; the red **OFF** badge means it is disconnected. **Auto capture** and **Tori only** are enabled initially; click their separate buttons to change behavior. The selection remains saved. No API token is needed. Reload open download pages after replacing the extension.
5. Click a public direct `.zip` or `.pdf` file link with Auto capture ON. To try video capture, open a public video page, click the small Tori button at the top-right of its visible video, then choose quality or MP3, filename, and folder in the app. Tori opens a confirmation dialog; choose the filename and folder and click **Download**. Test **Cancel** on another link: it should create no Tori job. Click **Settings** to change the default save folder. Manual **New URL** still asks for a filename and folder.

If you already have an older installed app, choose **Quit** in its window or tray before starting v0.22; only one instance can own the local connector port. Browsers cannot let an EXE silently install an extension. Loading the unpacked extension once is required. After installing the new extension, refresh open download pages. Keep Tori running while Tori only is ON.

## Background and sign-in startup

The installed build registers itself for the current user at first launch. The portable build defaults to sign-in startup OFF; turn it ON from Settings if desired. The next sign-in starts enabled builds hidden in the system tray. Press X to keep it running; use the tray icon to open or quit. Minimize keeps the app in the taskbar. The Settings switch can disable or restore sign-in startup. The confirmation window opens visibly even if Tori was hidden. Startup runs when you sign in to your Windows account, not before sign-in. Windows can defer startup briefly. The installer removes its sign-in entry when uninstalled. If the tray dependency cannot start, Tori stays visible instead of silently hiding.

## Make a Windows EXE

On Windows run `build-windows.bat` to create both releases in `release-dist`. It finds Inno Setup 6 in the standard installation locations or on PATH. The project ZIP contains source and the release builder, not prebuilt Windows binaries. An unsigned personal build may trigger SmartScreen; building and code signing need to happen on Windows.

## Capabilities and limits

- Downloads stream to `.part` files and are finalized after byte-count checks. Queue state survives app restarts. Resume uses HTTP Range and If-Range when available; up to three files can download at once. This limits concurrent jobs, not transfer bandwidth.
- Video page downloads use the separately bundled yt-dlp engine, with FFmpeg for streams that need merging. Provider changes, authentication, access controls and DRM can prevent a video download. The site may limit available quality or transfer speed. MP3 conversion cannot improve the source audio quality; encoding may take extra time.
- Direct file clicks are held until the app confirms Download or Cancel. Address-bar, script, and unsupported page downloads may begin in Chrome before its `onCreated` event is delivered. Tori only cancels the browser item immediately after that event, then asks in the app. Tiny files might finish before cancellation; such files remain visible in Chrome and are not offered a second time. Tori only does not block non-HTTP(S) downloads or downloads made while Auto capture is OFF, and cannot prevent every initial browser byte or popup. With Tori only OFF, failed handoffs resume in Chrome.
- Session-based files, POST requests, anti-bot sites, streaming video and downloads requiring browser cookies are not fully supported. Signed URLs can expire after initial checks. The connector listens on `127.0.0.1:8765` and trusts the fixed Tori extension ID; a separate local process may spoof its headers on the same PC.
- This environment cannot run or visually inspect the Windows GUI or EXE. Test the UI, installed build, browser handoff, large files and interrupted downloads on your Windows machine before using it for important files.

## Verification

Run `py -3 -m unittest discover -s tests -v`. The Python tests exercise full downloads, resume, collisions, folder choices, filename selection, HTML rejection and connector checks against a local test server. If Node.js is installed, run `node tests/test_extension.js` for browser handoff checks.

## Existing data

The installed version keeps queue metadata in `%LOCALAPPDATA%\FrejaDownloadManager` and older downloads in `%USERPROFILE%\Downloads\Freja Downloads`. Its default download folder is saved in `%LOCALAPPDATA%\FrejaDownloadManager\settings.json`. The portable ZIP keeps its queue, settings and default downloads in `ToriData` and `Downloads` beside the EXE; each job records its own folder. If you choose an external save folder, its path remains absolute and will not follow a moved portable ZIP. The old pairing token file is unused. The fixed Chromium extension ID is `fabmofikglnnbbobdhfcnlcneebfffhn`; if a browser assigns a different ID to the unpacked extension, connection will fail.
