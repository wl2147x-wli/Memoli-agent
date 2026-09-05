import { app, Tray, Menu, BrowserWindow, nativeImage } from 'electron'

let tray: Tray | null = null

interface TrayDeps {
  getWindow: () => BrowserWindow | null
  // Windows/Linux 托盘上使用的彩色图标。
  iconPath?: string
  // 当用户选择“退出”时调用，以便应用程序可以完全退出。
  onQuit: () => void
}

// 构建一个带有最小菜单的系统托盘图标（仅限 Windows/Linux — macOS
// 使用 Dock 来代替）。允许用户在关闭窗口后恢复窗口
// 背景并快速开始新的聊天。
export function createTray({ getWindow, iconPath, onQuit }: TrayDeps): Tray | null {
  if (tray) return tray
  if (!iconPath) return null

  let image = nativeImage.createFromPath(iconPath)
  if (image.isEmpty()) return null
  // 托盘图标变小；调整大小以避免在某些平台上出现过大的图像。
  image = image.resize({ width: 18, height: 18 })

  tray = new Tray(image)
  tray.setToolTip(app.name)

  const showWindow = () => {
    const win = getWindow()
    if (!win) return
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
  }

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show CowAgent', click: showWindow },
    {
      label: 'New Chat',
      click: () => {
        showWindow()
        getWindow()?.webContents.send('menu-action', 'new-chat')
      },
    },
    { type: 'separator' },
    { label: 'Quit', click: onQuit },
  ])
  tray.setContextMenu(contextMenu)

  // 单击即可恢复窗口（常见的 Windows/Linux 行为）。
  tray.on('click', showWindow)

  return tray
}

// 实时托盘实例（仅限 Windows/Linux），因此其图标可以在
// 运行时。在 macOS 上或在 createTray() 之前为 Null。
export function getTray(): Tray | null {
  return tray
}

export function destroyTray() {
  tray?.destroy()
  tray = null
}
