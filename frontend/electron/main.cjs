const { app, BrowserWindow, Menu, Tray, globalShortcut, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const http = require("node:http");
const fs = require("node:fs");

const BACKEND_URL = "http://127.0.0.1:8000";
let mainWindow;
let miniWindow;
let backendProcess;
let tray;
let isQuitting = false;
let miniExpandedBounds;

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
}

const TRAY_ICON = nativeImage.createFromDataURL(
  "data:image/svg+xml;charset=utf-8," +
    encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
        <rect width="64" height="64" rx="16" fill="#146b63"/>
        <circle cx="32" cy="24" r="11" fill="#f7f3ea"/>
        <path d="M18 47c3-10 25-10 28 0" fill="none" stroke="#f7f3ea" stroke-width="7" stroke-linecap="round"/>
        <circle cx="28" cy="23" r="2.5" fill="#146b63"/>
        <circle cx="36" cy="23" r="2.5" fill="#146b63"/>
      </svg>`
    )
);

function backendPython() {
  const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..", "..");
  const winPython = path.join(root, "backend", ".venv", "Scripts", "python.exe");
  if (process.platform === "win32" && fs.existsSync(winPython)) return winPython;
  return "python";
}

function startBackend() {
  if (backendProcess) return;
  const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..", "..");
  const backendDir = path.join(root, "backend");
  backendProcess = spawn(backendPython(), ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], {
    cwd: backendDir,
    windowsHide: true,
    stdio: "ignore",
  });
  backendProcess.on("exit", () => {
    backendProcess = null;
  });
}

function waitForBackend(timeoutMs = 12000) {
  const started = Date.now();
  return new Promise((resolve) => {
    const check = () => {
      http
        .get(`${BACKEND_URL}/api/health`, (res) => {
          res.resume();
          resolve(true);
        })
        .on("error", () => {
          if (Date.now() - started > timeoutMs) resolve(false);
          else setTimeout(check, 500);
        });
    };
    check();
  });
}

async function createWindow() {
  const alreadyRunning = await waitForBackend(1200);
  if (!alreadyRunning) startBackend();
  await waitForBackend();
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 980,
    minWidth: 1180,
    minHeight: 760,
    title: "Chinna Personal Agent",
    backgroundColor: "#f7f3ea",
    show: !app.isPackaged,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (app.isPackaged) {
    await mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  } else {
    await mainWindow.loadURL("http://127.0.0.1:5173");
  }

  mainWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    mainWindow.hide();
    if (miniWindow) miniWindow.show();
  });
}

async function createMiniWindow() {
  miniWindow = new BrowserWindow({
    width: 420,
    height: 390,
    minWidth: 330,
    minHeight: 360,
    x: 20,
    y: 80,
    title: "Chinna Mini",
    alwaysOnTop: true,
    resizable: true,
    frame: false,
    skipTaskbar: false,
    backgroundColor: "#f7f3ea",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  await miniWindow.loadFile(path.join(__dirname, "mini.html"));
  miniWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    miniWindow.hide();
  });
}

function showMainWindow() {
  if (!mainWindow) return;
  mainWindow.show();
  mainWindow.focus();
}

function showMiniWindow() {
  if (!miniWindow) return;
  expandMiniWindow();
  miniWindow.show();
  miniWindow.focus();
}

function collapseMiniWindow() {
  if (!miniWindow) return;
  miniExpandedBounds = miniWindow.getBounds();
  miniWindow.setMinimumSize(72, 72);
  miniWindow.setResizable(false);
  miniWindow.setSize(72, 72, true);
  miniWindow.webContents.send("omnipilot-mini-collapsed", true);
}

function expandMiniWindow() {
  if (!miniWindow) return;
  miniWindow.setResizable(true);
  miniWindow.setMinimumSize(330, 360);
  const bounds = miniExpandedBounds || { width: 420, height: 390 };
  miniWindow.setSize(Math.max(bounds.width, 420), Math.max(bounds.height, 390), true);
  miniWindow.webContents.send("omnipilot-mini-collapsed", false);
}

function updateTray() {
  if (!tray) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Chinna Console", click: showMainWindow },
      { label: "Show Desktop Mini", click: showMiniWindow },
      { type: "separator" },
      { label: "Start Wake Listener", click: () => apiRequest("/api/operator/voice-listener/start", "POST") },
      { label: "Stop Wake Listener", click: () => apiRequest("/api/operator/voice-listener/stop", "POST") },
      { label: "Wake", click: () => apiRequest("/api/operator/session/wake", "POST") },
      { label: "Sleep", click: () => apiRequest("/api/operator/session/sleep", "POST") },
      { label: "Emergency Stop", click: () => apiRequest("/api/operator/session/stop", "POST") },
      { type: "separator" },
      { label: "Open Private Vault", click: () => shell.openPath(path.join(process.env.LOCALAPPDATA || app.getPath("userData"), "PavanPrivateApp")) },
      {
        label: "Quit Chinna",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ])
  );
}

function createTray() {
  tray = new Tray(TRAY_ICON);
  tray.setToolTip("Chinna Personal Agent is running on your desktop");
  tray.on("click", showMiniWindow);
  updateTray();
}

function configureStartWithWindows() {
  if (process.platform !== "win32") return;
  if (app.isPackaged) {
    app.setLoginItemSettings({
      openAtLogin: true,
      path: process.execPath,
    });
  }
}

async function enableDesktopPresence() {
  configureStartWithWindows();
  await apiRequest("/api/operator/session/sleep", "POST");
  await apiRequest("/api/operator/voice-listener/start", "POST");
  miniWindow?.webContents.send("omnipilot-refresh");
}

function apiRequest(route, method = "GET", body) {
  return new Promise((resolve) => {
    const payload = body ? JSON.stringify(body) : "";
    const req = http.request(
      `${BACKEND_URL}${route}`,
      {
        method,
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => {
          data += chunk;
        });
        res.on("end", () => {
          resolve(data);
        });
      }
    );
    req.on("error", () => resolve(""));
    if (payload) req.write(payload);
    req.end();
  });
}

if (gotSingleInstanceLock) {
  app.whenReady().then(async () => {
    await createWindow();
    await createMiniWindow();
    createTray();
    await enableDesktopPresence();
    showMiniWindow();
    globalShortcut.register("Alt+Space", () => {
      mainWindow?.webContents.send("omnipilot-hotkey");
      showMiniWindow();
    });
  });
}

app.on("second-instance", () => {
  showMiniWindow();
  showMainWindow();
});

ipcMain.handle("open-external", async (_event, url) => {
  await shell.openExternal(url);
});

ipcMain.handle("show-main", async () => {
  showMainWindow();
});

ipcMain.handle("show-mini", async () => {
  showMiniWindow();
});

ipcMain.handle("hide-mini", async () => {
  miniWindow?.hide();
});

ipcMain.handle("collapse-mini", async () => {
  collapseMiniWindow();
});

ipcMain.handle("expand-mini", async () => {
  expandMiniWindow();
  showMiniWindow();
});

ipcMain.handle("quit-app", async () => {
  isQuitting = true;
  app.quit();
});

app.on("window-all-closed", () => {
  if (process.platform === "darwin") return;
});

app.on("before-quit", () => {
  isQuitting = true;
  globalShortcut.unregisterAll();
  if (backendProcess) backendProcess.kill();
});
