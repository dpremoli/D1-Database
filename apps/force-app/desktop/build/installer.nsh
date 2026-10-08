; Extra NSIS steps, picked up by electron-builder from build/installer.nsh (nsis.include in
; electron-builder.yml names it explicitly).
;
; Uninstall removes the per-user "ForceAppUpdateCheck" scheduled task (desktop/src/updateTask.ts:
; UPDATE_TASK_NAME) that notifies about updates while the app is closed, or Windows would keep
; trying to launch an exe that is gone. Not on an update: electron-builder runs the old uninstaller
; silently first, and the app should keep its task across it. The installer is perMachine: false,
; so this runs as the installing user, the one the task belongs to. A missing task is not an error.
!macro customUnInstall
  ${ifNot} ${isUpdated}
    nsExec::Exec 'schtasks /delete /tn "ForceAppUpdateCheck" /f'
    Pop $0
  ${endIf}
!macroend
